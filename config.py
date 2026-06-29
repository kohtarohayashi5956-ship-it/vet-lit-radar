# -*- coding: utf-8 -*-
"""巡回設定。ここだけ編集すれば対象誌・トピック・閾値を変えられます。"""

# --- 巡回対象誌（PubMedのジャーナル略称）---------------------------------
# 起動前に `python fetch_and_digest.py --check-journals` で各略称が
# 件数>0 で解決するか必ず確認してください（特にJVECCは表記揺れに注意）。
JOURNALS = [
    "J Vet Intern Med",                 # JVIM
    "J Small Anim Pract",               # JSAP
    "J Feline Med Surg",                # JFMS
    "J Vet Emerg Crit Care (San Antonio)",  # JVECC
    "J Am Vet Med Assoc",               # JAVMA
    "Am J Vet Res",                     # AJVR
    "Vet Rec",                          # Veterinary Record
    "Vet J",                            # The Veterinary Journal
    "J Vet Med Sci",                    # JVMS
    "BMC Vet Res",                      # BMC Veterinary Research
    "Front Vet Sci",                    # Frontiers in Veterinary Science
]

# --- 種の絞り込み（title/abstract）----------------------------------------
SPECIES = ["dog", "dogs", "canine", "cat", "cats", "feline"]

# --- トピック群（title/abstractのフリーテキスト）--------------------------
# キーには日本語のトピック名、値に拾いたい英語キーワード。
# 新規論文はMeSH未付与のことが多いので、あえて[tiab]フリーテキストで拾う。
TOPIC_GROUPS = {
    "消化器": ["enteropathy", "chronic enteropathy", "inflammatory bowel disease",
               "protein-losing enteropathy", "colitis", "gastrointestinal", "enteritis"],
    "肝胆膵": ["hepatopathy", "hepatitis", "cholangitis", "cholangiohepatitis",
               "gallbladder", "biliary", "pancreatitis", "pancreatic"],
    "リンパ腫": ["lymphoma"],
    "副腎": ["hyperadrenocorticism", "Cushing", "hypoadrenocorticism", "Addison",
             "adrenal", "pheochromocytoma"],
    "甲状腺": ["hyperthyroidism", "hypothyroidism", "thyroid"],
    "MMVD": ["myxomatous mitral valve", "mitral valve", "degenerative valve",
             "endocardiosis"],
    "心筋症": ["cardiomyopathy"],
    "腎臓": ["chronic kidney disease", "acute kidney injury", "renal", "kidney",
             "proteinuria", "glomerular", "nephropathy"],
    "IMHA/ITP": ["immune-mediated hemolytic anemia", "immune mediated hemolytic anemia",
                 "immune thrombocytopenia", "immune-mediated thrombocytopenia"],
    "FIP": ["feline infectious peritonitis", "GS-441524", "remdesivir", "molnupiravir"],
    "免疫療法": ["immunotherapy", "checkpoint inhibitor", "PD-1", "PD-L1", "CTLA-4",
                "monoclonal antibody"],
}

# --- 動作パラメータ -------------------------------------------------------
RELDATE = 3 # 直近何日分（EDAT基準）を巡回するか。日次なら2-3で重複margin
MAX_FETCH = 400             # esearchで取る最大PMID数
MAX_PAPERS_PER_RUN = 80     # 1回でClaude評価にかける新規論文の上限（暴走防止）
MIN_USEFULNESS = 3          # この点未満は掲載しない（1-5）

# Anthropicモデル。量が多くコストを抑えたいなら "claude-haiku-4-5-20251001" に。
MODEL = "claude-sonnet-4-6"

SITE_TITLE = "Vet Lit Radar — 小動物内科 新着論文"
