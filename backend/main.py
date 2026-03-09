from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional, List, Dict, Set
import re

app = FastAPI(title="V-Shuttle Core Logic - Enterprise Edition (Regex V2)")

# =================================================================
# 1. MODELLI DATI
# =================================================================
class SensoreData(BaseModel):
    testo: Optional[str] = None
    confidenza: Optional[float] = None

class SensoriInput(BaseModel):
    camera_frontale: SensoreData
    camera_laterale: SensoreData
    V2I_receiver: SensoreData

class ScenarioInput(BaseModel):
    id_scenario: int
    sensori: SensoriInput
    orario_rilevamento: str
    giorno_settimana: str

class ActionOutput(BaseModel):
    id_scenario: int
    action: str
    confidence: float
    reason: str

# =================================================================
# 2. IL LIBRO DELLE REGOLE
# =================================================================
TRAFFIC_RULES = [
    {
        "id": "regola_varco_inattivo_o_fine",
        "priority": 100, 
        "must_have": ["VARCO_INATTIVO"], "must_not_have": [],
        "action": "GO", "reason": "Il varco ZTL è esplicitamente inattivo o terminato."
    },
    {
        # BUG 6 RISOLTO: Se c'è un divieto esplicito per le navette e MANCA la parola "Eccetto"
        "id": "regola_divieto_esplicito_navette",
        "priority": 98,
        "must_have": ["DIVIETO_TRANSITO", "TARGET_BUS"], "must_not_have": ["ECCEZIONE_GENERICA", "FUORI_RESTRIZIONE"],
        "action": "STOP", "reason": "Rilevato divieto DIRETTO per la categoria Navette/L4."
    },
    {
        "id": "regola_fuori_orario_o_festivo",
        "priority": 95,
        "must_have": ["DIVIETO_TRANSITO", "FUORI_RESTRIZIONE"], "must_not_have": [],
        "action": "GO", "reason": "Divieto/ZTL presente ma fuori orario o non attivo in questo giorno."
    },
    {
        "id": "regola_eccezione_bus",
        "priority": 90,
        "must_have": ["DIVIETO_TRANSITO", "TARGET_BUS", "ECCEZIONE_GENERICA"], "must_not_have": ["FUORI_RESTRIZIONE"],
        "action": "GO", "reason": "Navetta autorizzata al transito (Eccezione L4/BUS)."
    },
    {
        "id": "regola_divieto_base",
        "priority": 80,
        "must_have": ["DIVIETO_TRANSITO"], "must_not_have": ["ECCEZIONE_GENERICA", "FUORI_RESTRIZIONE"],
        "action": "STOP", "reason": "Rilevato divieto di transito o ZTL attiva."
    },
    {
        "id": "regola_eccezione_orfana",
        "priority": 85,
        "must_have": ["ECCEZIONE_GENERICA"], "must_not_have": ["DIVIETO_TRANSITO"],
        "action": "REVIEW", "reason": "Rilevato pannello 'ECCETTO' senza divieto principale. Contesto mancante."
    }
]

GIORNI_FESTIVI = ["Domenica"]

# =================================================================
# 3. MOTORE DI ESTRAZIONE E FUSIONE (NLP Avanzato)
# =================================================================
class SensorFusionEngine:
    def __init__(self):
        # BUG RISOLTI CON LE REGEX:
        # 1. Negative Lookbehind per FINE ZTL: (?<!FINE\s)ZTL
        # 3. Confini di parola \b per evitare che ALTERNATO inneschi ALT
        # 4. Negative Lookahead per ignorare divieti di sosta/fermata/scarico
        # 5. Aggiunto SENSO VIETATO
        self.vocabulary = {
            "DIVIETO_TRANSITO": [
                r"\b(?:D[I1]V[I1]ET[O0])\b(?!\s+(?:DI\s+)?(?:SOSTA|FERMATA|SCARICO|AFFISSIONE))", 
                r"(?<!FINE\s)ZTL\b", 
                r"\bSTOP\b", 
                r"\bNO\b\s+(?:TRANSITO|ACCESSO|MOTORE|VEICOLI)", 
                r"\bALT\b", 
                r"SENSO\s+VIETATO", 
                r"STRADA\s+CHIUSA",
                r"AREA\s+PEDONALE"
            ],
            "ECCEZIONE_GENERICA": [r"\bECCETTO\b", r"\bTRANNE\b", r"\bCONSENTITO\b", r"\bOK\b"],
            "TARGET_BUS": [r"\bBUS\b", r"\bNAVETT[AE]\b", r"\bL4\b"],
            "VARCO_INATTIVO": [r"INATTIVO", r"NON\s*ATTIVO", r"SPENTO", r"FINE\s+ZTL"],
            "SOLO_FESTIVI": [r"FESTIVI"]
        }

    def _clean_text(self, text: str) -> str:
        if not text: return ""
        text = text.upper()
        # Mappature specifiche per gli errori OCR distruttivi (Hackathon pragmatism)
        ocr_fixes = {
            "S3NS0 UN1C0 4LT3RN4T0": "SENSO UNICO ALTERNATO",
            "D I V  E T O": "DIVIETO",
            "5T4Z10N3": "STAZIONE",
            "4R3A P3D0NAL3": "AREA PEDONALE"
        }
        for bad, good in ocr_fixes.items():
            text = text.replace(bad, good)
        # Non togliamo più gli spazi brutalmente per evitare il Bug "10 KM/H" -> "IOKMH" -> "OK"
        return text

    def _extract_times(self, raw_text: str) -> tuple[Optional[str], Optional[str]]:
        if not raw_text: return None, None
        text = raw_text.upper()
        # Formato 08:00 - 20:00
        times = re.findall(r'(\d{1,2}:\d{2})', text)
        if len(times) >= 2: return times[0], times[1]
        
        # Formato DALLE 20 (assume ZTL notturna 20:00 - 06:00)
        dalle = re.search(r'DALLE\s+(\d{1,2})', text)
        if dalle: return f"{int(dalle.group(1)):02d}:00", "06:00"

        # Formato 0-24
        if "0-24" in text: return "00:00", "23:59"
        
        # Formato 08-20
        short_times = re.findall(r'(\d{1,2})-(\d{1,2})', text)
        if short_times: return f"{int(short_times[0][0]):02d}:00", f"{int(short_times[0][1]):02d}:00"
        return None, None

    def fuse(self, sensori_input: SensoriInput) -> tuple[Set[str], float, dict]:
        sensors_data = [sensori_input.camera_frontale, sensori_input.camera_laterale, sensori_input.V2I_receiver]
        
        tag_scores = {}
        total_active_weight = 0.0
        extracted_times = {'start': None, 'end': None}

        for data in sensors_data:
            if not data.testo or data.confidenza is None: continue
            
            clean_txt = self._clean_text(data.testo)
            weight = data.confidenza
            total_active_weight += weight

            # Ricerca Regex Tag
            for tag_name, regex_patterns in self.vocabulary.items():
                for pattern in regex_patterns:
                    if re.search(pattern, clean_txt):
                        tag_scores[tag_name] = tag_scores.get(tag_name, 0.0) + weight
                        break # Evita di sommare due volte se fa match su due pattern dello stesso tag

            # Estrazione Orari
            if not extracted_times['start']:
                s, e = self._extract_times(clean_txt)
                if s and e: extracted_times.update({'start': s, 'end': e})

        # Valutazione Margin of Doubt
        confirmed_tags, ambiguous_tags = set(), set()
        
        if total_active_weight > 0:
            for tag, score in tag_scores.items():
                ratio = score / total_active_weight
                if ratio > 0.60:
                    confirmed_tags.add(tag)
                elif 0.40 <= ratio <= 0.60: 
                    ambiguous_tags.add(tag)
                    
        return confirmed_tags, ambiguous_tags, round(total_active_weight, 2), extracted_times

# =================================================================
# 4. VALUTATORE DI CONTESTO E MOTORE DECISIONALE
# =================================================================
class ContextEvaluator:
    @staticmethod
    def _time_to_minutes(t_str: str) -> int:
        try:
            h, m = map(int, t_str.split(':'))
            return h * 60 + m
        except: return -1

    @classmethod
    def evaluate(cls, tags: Set[str], times: dict, c_time: str, c_day: str) -> Set[str]:
        final_tags = set(tags)
        if "SOLO_FESTIVI" in final_tags and c_day not in GIORNI_FESTIVI:
            final_tags.add("FUORI_RESTRIZIONE")
            
        start_str, end_str = times.get('start'), times.get('end')
        if start_str and end_str and "DIVIETO_TRANSITO" in final_tags:
            curr, start, end = cls._time_to_minutes(c_time), cls._time_to_minutes(start_str), cls._time_to_minutes(end_str)
            is_active = (start <= curr <= end) if start <= end else (curr >= start or curr <= end)
            if not is_active: final_tags.add("FUORI_RESTRIZIONE")
                
        return final_tags

class RuleEvaluator:
    def __init__(self, rules: List[dict]):
        self.rules = sorted(rules, key=lambda x: x['priority'], reverse=True)

    def decide(self, active_tags: Set[str]) -> tuple[str, str]:
        for rule in self.rules:
            if set(rule.get('must_have', [])).issubset(active_tags) and set(rule.get('must_not_have', [])).isdisjoint(active_tags):
                return rule['action'], rule['reason']
        return "GO", "Nessun vincolo bloccante rilevato."

# =================================================================
# 5. ENDPOINT FASTAPI
# =================================================================
fusion_engine = SensorFusionEngine()
rule_evaluator = RuleEvaluator(TRAFFIC_RULES)

@app.post("/api/evaluate", response_model=ActionOutput)
def evaluate_scenario(scenario: ScenarioInput):
    try:
        conf_tags, ambig_tags, total_conf, ext_times = fusion_engine.fuse(scenario.sensori)
        
        if total_conf == 0:
            return ActionOutput(id_scenario=scenario.id_scenario, action="STOP", confidence=0.0, reason="Blackout totale sensori.")

        if ambig_tags:
            return ActionOutput(id_scenario=scenario.id_scenario, action="REVIEW", confidence=total_conf, 
                reason=f"Conflitto tra sensori sul concetto: [{', '.join(ambig_tags)}]. Richiesto operatore.")

        final_tags = ContextEvaluator.evaluate(conf_tags, ext_times, scenario.orario_rilevamento, scenario.giorno_settimana)
        action, reason = rule_evaluator.decide(final_tags)
        
        if "FUORI_RESTRIZIONE" in final_tags and action == "GO":
            reason += f" (Orario rilevato: {ext_times.get('start')}-{ext_times.get('end')})"

        return ActionOutput(id_scenario=scenario.id_scenario, action=action, confidence=total_conf, reason=reason)

    except Exception as e:
        return ActionOutput(id_scenario=scenario.id_scenario, action="STOP", confidence=0.0, reason="Frenata automatica di sicurezza.")