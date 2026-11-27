"""Gera data.json para a calculadora a partir dos repositorios oficiais da Receita Federal.

Uso: python build_data.py <calculadora-rtc-regime-regular> <calculadora-rtc-simples-nacional> <saida.json>

Monta o banco SQLite com os scripts Flyway do repositorio do regime regular (os mesmos que o
repositorio do Simples Nacional usa) e exporta as tabelas usadas no calculo.
"""
import glob, json, os, re, sqlite3, subprocess, sys, datetime

rr, sn, out = sys.argv[1], sys.argv[2], sys.argv[3]


def montar_banco(repo):
    con = sqlite3.connect(":memory:")
    base = os.path.join(repo, "flyway", "sql")
    scripts = [os.path.join(base, "criacao", "beforeMigrate.sql"),
               os.path.join(base, "criacao", "B0001__sistema_tributario_completo.sql")]
    mig = glob.glob(os.path.join(base, "manutencao", "V*.sql"))
    mig.sort(key=lambda p: int(re.match(r"V(\d+)", os.path.basename(p)).group(1)))
    scripts += mig + [os.path.join(base, "criacao", "afterMigrate.sql")]
    for s in scripts:
        if not os.path.exists(s):
            continue
        txt = open(s, encoding="utf-8").read()
        txt = re.sub(r"(?im)^\s*PRAGMA\s+(foreign_keys|journal_mode|mmap_size|page_size)\s*=.*?;", "", txt)
        con.execute("PRAGMA foreign_keys=OFF")
        con.executescript(txt)
    return con, len(scripts)


def commit(repo):
    try:
        return subprocess.check_output(["git", "-C", repo, "log", "-1", "--format=%h|%cI"], text=True).strip().split("|")
    except Exception:
        return ["", ""]


con, n_scripts = montar_banco(rr)
q = lambda sql, *a: con.execute(sql, a).fetchall()

# Tributos: 1 IS, 2 CBS, 3 IBSUF, 4 IBSMun
sigla = {tid: s for tid, s in q("select TBTO_ID, TBTO_SIGLA from TRIBUTO")}

# Situacoes tributarias do IBS/CBS (as do IS ficam separadas)
sit_trib = {}
for sid, tid in q("select TRST_SITR_ID, TRST_TBTO_ID from TRIBUTO_SITUACAO_TRIBUTARIA"):
    sit_trib.setdefault(sid, set()).add(tid)
sit_ibscbs = {sid for sid, t in sit_trib.items() if 2 in t}
sit_is = {sid for sid, t in sit_trib.items() if t == {1}}

# Aliquotas de referencia
aliq_ref = [{"t": sigla[t], "v": v, "ini": i, "fim": f}
            for v, i, f, t in q("select ALRE_VALOR, ALRE_INICIO_VIGENCIA, ALRE_FIM_VIGENCIA, ALRE_TBTO_ID from ALIQUOTA_REFERENCIA")]

# Tratamento tributario (formulas oficiais)
trat = {}
for row in q("""select tc.TRCL_CLTR_ID, tt.TRTR_DESCRICAO, tt.TRTR_EXPRESSAO_ALIQUOTA, tt.TRTR_EXPRESSAO_ALIQUOTA_EFETIVA,
                       tt.TRTR_EXPRESSAO_BASE_CALCULO, tt.TRTR_EXPRESSAO_TRIBUTO_CALCULADO, tt.TRTR_EXPRESSAO_TRIBUTO_DEVIDO,
                       tc.TRCL_INICIO_VIGENCIA, tc.TRCL_FIM_VIGENCIA
                from TRATAMENTO_CLASSIFICACAO tc join TRATAMENTO_TRIBUTARIO tt on tt.TRTR_ID = tc.TRCL_TRTR_ID"""):
    trat.setdefault(row[0], []).append({"desc": row[1], "aliq": row[2] or "", "aliqEfet": row[3] or "", "base": row[4] or "",
                                        "trib": row[5] or "", "devido": row[6] or "", "ini": row[7], "fim": row[8]})

# Percentuais de reducao por tributo e vigencia
red = {}
for cid, tid, v, i, f in q("select PERE_CLTR_ID, PERE_TBTO_ID, PERE_VALOR, PERE_INICIO_VIGENCIA, PERE_FIM_VIGENCIA from PERCENTUAL_REDUCAO"):
    red.setdefault(cid, []).append({"t": sigla.get(tid, str(tid)), "v": v, "ini": i, "fim": f})

# Classificacoes tributarias do IBS/CBS
cts = []
for r in q("""select ct.CLTR_ID, ct.CLTR_CD, s.SITR_CD, s.SITR_DESCRICAO, ct.CLTR_DESCRICAO, ct.CLTR_TIPO_ALIQUOTA,
                     ct.CLTR_NOMENCLATURA, ct.CLTR_IN_APROPRIACAO_CREDITOS_ADQUIRENTES_CBS,
                     ct.CLTR_IN_APROPRIACAO_CREDITOS_ADQUIRENTES_IBS, ct.CLTR_TPRBSN, ct.CLTR_INICIO_VIGENCIA,
                     ct.CLTR_FIM_VIGENCIA, ct.CLTR_SITR_ID
              from CLASSIFICACAO_TRIBUTARIA ct join SITUACAO_TRIBUTARIA s on s.SITR_ID = ct.CLTR_SITR_ID
              order by ct.CLTR_CD, ct.CLTR_INICIO_VIGENCIA"""):
    if r[12] not in sit_ibscbs:
        continue
    cts.append({"id": r[0], "cd": r[1], "cst": r[2], "cstDesc": r[3], "desc": r[4], "tipo": r[5], "nom": r[6],
                "credCBS": r[7], "credIBS": r[8], "tpRBSN": r[9], "ini": r[10], "fim": r[11],
                "red": red.get(r[0], []), "trat": trat.get(r[0], [])})
ct_ids = {c["id"]: c["cd"] for c in cts}

# Vinculo NCM x cClassTrib (com excecoes)
exc = {}
for ncm, ncma, i, f in q("select ENCM_NCM_CD, ENCM_NCMA_ID, ENCM_INICIO_VIGENCIA, ENCM_FIM_VIGENCIA from EXCECAO_NCM_APLICAVEL"):
    exc.setdefault(ncma, []).append({"ncm": ncm, "ini": i, "fim": f})
ncm_ibscbs, ncm_is = [], []
for ncma, ncm, cid, sid, i, f in q("""select n.NCMA_ID, n.NCMA_NCM_CD, n.NCMA_CLTR_ID, ct.CLTR_SITR_ID, n.NCMA_INICIO_VIGENCIA, n.NCMA_FIM_VIGENCIA
                                     from NCM_APLICAVEL n join CLASSIFICACAO_TRIBUTARIA ct on ct.CLTR_ID = n.NCMA_CLTR_ID"""):
    item = {"p": ncm, "ini": i, "fim": f}
    if ncma in exc:
        item["exc"] = exc[ncma]
    if cid in ct_ids:
        item["cd"] = ct_ids[cid]
        ncm_ibscbs.append(item)
    elif sid in sit_is:
        ncm_is.append(item)

# NCM com aliquota ad valorem do IS cadastrada (o valor pode ainda nao estar definido em lei)
is_prod = [{"p": ncm, "v": v, "ini": i, "fim": f} for ncm, v, i, f in q(
    """select p.AAVP_NCM_CD, a.AADV_VALOR, p.AAVP_INICIO_VIGENCIA, p.AAVP_FIM_VIGENCIA
       from ALIQUOTA_AD_VALOREM_PRODUTO p join ALIQUOTA_AD_VALOREM a on a.AADV_ID = p.AAVP_AADV_ID""")]

# Simples Nacional
atividades = [{"c": c, "desc": d, "anexo": a, "anexoFatorR": afr, "rotulo": rot, "naoTrib": nt, "ini": i, "fim": f}
              for c, d, a, afr, rot, nt, i, f in q(
                  """select ATSN_CATIVSN, ATSN_DESCRICAO, ATSN_ANEXO_SEM_FATOR_R, ATSN_ANEXO_COM_FATOR_R, ATSN_ROTULO_CURTO,
                            ATSN_IN_NAO_TRIBUTAVEL, ATSN_INICIO_VIGENCIA, ATSN_FIM_VIGENCIA
                     from ATIVIDADE_SIMPLES_NACIONAL order by ATSN_ORDEM""")]
tipos_receita = [{"cd": c, "desc": d, "compoe": comp, "fator": fat, "pend": pend, "exige": ex, "ini": i, "fim": f}
                 for c, d, comp, fat, pend, ex, i, f in q(
                     """select TRBS_CD, TRBS_DESCRICAO, TRBS_IN_COMPOE_RECEITA, TRBS_FATOR_RECEITA, TRBS_IN_PENDENTE_SUSPENSO,
                               TRBS_IN_EXIGE_ALIQUOTA, TRBS_INICIO_VIGENCIA, TRBS_FIM_VIGENCIA
                        from TIPO_RECEITA_BRUTA_SIMPLES_NACIONAL where TRBS_VOCABULARIO_REGIME is null""")]
regimes_sn = [{"cd": c, "desc": d, "calcula": ca, "geraIbs": gi, "devido": dv, "pend": pe, "ini": i, "fim": f}
              for c, d, ca, gi, dv, pe, i, f in q(
                  """select RASN_CD, RASN_DESCRICAO, RASN_IN_CALCULA_TRIBUTOS, RASN_IN_GERA_IBS, RASN_DESTINO_DEVIDO,
                            RASN_DESTINO_PENDENTE_SUSPENSO, RASN_INICIO_VIGENCIA, RASN_FIM_VIGENCIA
                     from REGIME_APURACAO_SIMPLES_NACIONAL""")]

versao = q("select VRBD_VERSAO_BASE_DADO, VRBD_DATA, VRBD_DESCRICAO from VERSAO_BASE_DADO order by VRBD_ID desc limit 1")
rr_commit, sn_commit = commit(rr), commit(sn)

data = {
    "meta": {
        "versaoBase": versao[0][0] if versao else "", "dataBase": (versao[0][1] or "")[:10] if versao else "",
        "descricaoBase": versao[0][2] if versao else "",
        "geradoEm": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "scripts": n_scripts,
        "fontes": [
            {"repo": "ReceitaFederal/calculadora-rtc-regime-regular", "commit": rr_commit[0], "data": rr_commit[1]},
            {"repo": "ReceitaFederal/calculadora-rtc-simples-nacional", "commit": sn_commit[0], "data": sn_commit[1]},
        ],
    },
    "aliqRef": aliq_ref,
    "cClassTrib": cts,
    "ncmIbsCbs": ncm_ibscbs,
    "ncmIs": ncm_is,
    "isProduto": is_prod,
    "simples": {"atividades": atividades, "tiposReceita": tipos_receita, "regimes": regimes_sn},
}
os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
with open(out, "w", encoding="utf-8") as fh:
    json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
print(f"data.json: {len(cts)} cClassTrib, {len(ncm_ibscbs)} vinculos NCM, {len(ncm_is)} NCM do IS, "
      f"base {data['meta']['versaoBase']} ({data['meta']['dataBase']}), {os.path.getsize(out)} bytes")
