from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional, List, Set, Tuple
import re

app = FastAPI(title="V-Shuttle Core Logic - Enterprise Edition")

# =================================================================
# 1. MODELLI DATI (Allineati al JSON di Hastega)
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
    action: str          # SOLO "GO" o "STOP"
    needs_review: bool   # TRUE se serve l'intervento di Marco, altrimenti FALSE
    confidence: float
    reason: str

# =================================================================
# 2. IL LIBRO DELLE REGOLE (Rule Engine Disaccoppiato)
# =================================================================
TRAFFIC_RULES = [
    {
        "id": "regola_varco_inattivo_o_fine",
        "priority": 100, 
        "must_have": ["VARCO_INATTIVO"], "must_not_have": [],
        "action": "GO", "needs_review": False,
        "reason": "Il varco ZTL è esplicitamente inattivo o terminato."
    },
    {
        "id": "regola_divieto_esplicito_navette",
        "priority": 98,
        "must_have": ["DIVIETO_TRANSITO", "TARGET_BUS"], "must_not_have": ["ECCEZIONE_GENERICA", "FUORI_RESTRIZIONE"],
        "action": "STOP", "needs_review": False,
        "reason": "Rilevato divieto DIRETTO per la categoria Navette/L4."
    },
    {
        "id": "regola_fuori_orario_o_festivo",
        "priority": 95,
        "must_have": ["DIVIETO_TRANSITO", "FUORI_RESTRIZIONE"], "must_not_have": [],
        "action": "GO", "needs_review": False,
        "reason": "Divieto/ZTL presente ma fuori orario o non attivo in questo giorno."
    },
    {
        "id": "regola_eccezione_bus",
        "priority": 90,
        "must_have": ["DIVIETO_TRANSITO", "TARGET_BUS", "ECCEZIONE_GENERICA"], "must_not_have": ["FUORI_RESTRIZIONE"],
        "action": "GO", "needs_review": False,
        "reason": "Navetta autorizzata al transito (Eccezione L4/BUS)."
    },
    {
        "id": "regola_divieto_eccezione_altri",
        "priority": 85,
        "must_have": ["DIVIETO_TRANSITO", "ECCEZIONE_GENERICA"], "must_not_have": ["TARGET_BUS", "FUORI_RESTRIZIONE"],
        "action": "STOP", "needs_review": False,
        "reason": "Rilevato divieto con eccezioni, ma la nostra navetta NON è tra i mezzi autorizzati."
    },
    {
        "id": "regola_divieto_base",
        "priority": 80,
        "must_have": ["DIVIETO_TRANSITO"], "must_not_have": ["ECCEZIONE_GENERICA", "FUORI_RESTRIZIONE"],
        "action": "STOP", "needs_review": False,
        "reason": "Rilevato divieto di transito o ZTL attiva."
    },
    {
        "id": "regola_eccezione_orfana",
        "priority": 85,
        "must_have": ["ECCEZIONE_GENERICA"], "must_not_have": ["DIVIETO_TRANSITO"],
        "action": "STOP", "needs_review": True, # Forziamo lo Stop sicuro, ma chiamiamo Marco
        "reason": "Rilevato pannello 'ECCETTO' senza divieto principale. Contesto mancante."
    }
]

GIORNI_FESTIVI = ["Domenica"]

# =================================================================
# 3. MOTORE DI ESTRAZIONE E FUSIONE SENSORIALE (Data-Driven NLP)
# =================================================================
# =================================================================
# 3. MOTORE DI ESTRAZIONE E FUSIONE (Ottimizzato per Scenario 3)
# =================================================================
class SensorFusionEngine:
    def __init__(self):
        self.vocabulary = {
            "DIVIETO_TRANSITO": [
                # Rimosso \b per gestire parole attaccate (es. ZTLATTIVA)
                r"(?<!FINE\s)Z\s*T\s*L", 
                r"DIVIETO(?!.*(?:SOSTA|FERMATA|SCARICO|AFFISSIONE))", 
                r"ACCESSO", 
                r"STOP", 
                r"VIETATO", 
                r"CHIUSA", 
                r"MERCATO", 
                r"PESANTI", 
                r"ALT"
            ],
            "ECCEZIONE_GENERICA": [r"ECCETTO", r"TRANNE", r"CONSENTITO", r"OK"],
            "TARGET_BUS": [r"BUS", r"NAVETT[AE]", r"L4", r"AUTORIZZATI"],
            "VARCO_INATTIVO": [r"INATTIVO", r"NON\s*ATTIVO", r"SPENTO", r"FINE\s+Z\s*T\s*L"],
            "SOLO_FESTIVI": [r"FESTIVI"]
        }

    def _clean_text(self, text: str) -> str:
        if not text: return ""
        text = text.upper()
        # Normalizzazione OCR standard
        text = text.replace('0', 'O').replace('1', 'I').replace('5', 'S').replace('8', 'B')
        # NON rimuoviamo tutti gli spazi qui per permettere alle regex di funzionare meglio
        return text

    def _extract_times(self, raw_text: str) -> Tuple[Optional[str], Optional[str]]:
        """Estrae orari gestendo vari formati (08:00, 08-20, 8:00)."""
        if not raw_text: return None, None
        
        # 1. Cerca formato HH:MM (es. 08:00 o 8:00)
        times = re.findall(r'(\d{1,2}:\d{2})', raw_text)
        if len(times) >= 2:
            return times[0], times[1]
            
        # 2. Cerca formato HH-HH (es. 08-20)
        short_times = re.findall(r'(\d{1,2})-(\d{1,2})', raw_text)
        if short_times:
            return f"{int(short_times[0][0]):02d}:00", f"{int(short_times[0][1]):02d}:00"
            
        return None, None

    def fuse(self, sensori_input: SensoriInput) -> Tuple[Set[str], Set[str], float, dict]:
        sensors_data = [sensori_input.camera_frontale, sensori_input.camera_laterale, sensori_input.V2I_receiver]
        tag_scores = {}
        total_active_weight = 0.0
        extracted_times = {'start': None, 'end': None}

        for data in sensors_data:
            if not data.testo or data.confidenza is None: continue
            
            clean_txt = self._clean_text(data.testo)
            weight = data.confidenza
            total_active_weight += weight

            # Ricerca Tag
            for tag_name, regex_patterns in self.vocabulary.items():
                for pattern in regex_patterns:
                    if re.search(pattern, clean_txt):
                        tag_scores[tag_name] = tag_scores.get(tag_name, 0.0) + weight
                        break

            # Estrazione Orari: Priorità al sensore con confidenza più alta
            if not extracted_times['start']:
                s, e = self._extract_times(clean_txt)
                if s and e:
                    extracted_times['start'], extracted_times['end'] = s, e

        confirmed_tags, ambiguous_tags = set(), set()
        if total_active_weight > 0:
            for tag, score in tag_scores.items():
                ratio = score / total_active_weight
                if ratio > 0.60: confirmed_tags.add(tag)
                elif 0.40 <= ratio <= 0.60: ambiguous_tags.add(tag)
                    
        return confirmed_tags, ambiguous_tags, round(total_active_weight, 2), extracted_times

# =================================================================
# 4. VALUTATORE DI CONTESTO (Ottimizzato per Scenario 3)
# =================================================================
class ContextEvaluator:
    @staticmethod
    def _time_to_minutes(t_str: str) -> int:
        try:
            # Gestisce sia "08:00" che "8:00"
            h, m = map(int, t_str.split(':'))
            return h * 60 + m
        except: return -1

    @classmethod
    def evaluate(cls, tags: Set[str], times: dict, c_time: str, c_day: str) -> Set[str]:
        final_tags = set(tags)
        
        # Check Festivi
        if "SOLO_FESTIVI" in final_tags and c_day not in GIORNI_FESTIVI:
            final_tags.add("FUORI_RESTRIZIONE")
            return final_tags

        # Check Orari (Caso Scenario 3: 10:00 vs 08:00-20:00)
        start_str, end_str = times.get('start'), times.get('end')
        if start_str and end_str and "DIVIETO_TRANSITO" in final_tags:
            curr = cls._time_to_minutes(c_time)
            start = cls._time_to_minutes(start_str)
            end = cls._time_to_minutes(end_str)
            
            # Logica range orario
            if start <= end:
                is_active = (start <= curr <= end)
            else: # Notturno (es. 22-06)
                is_active = (curr >= start or curr <= end)
            
            # Se siamo FUORI dal range, aggiungiamo il tag per il GO
            if not is_active:
                final_tags.add("FUORI_RESTRIZIONE")
            # Se siamo DENTRO il range (come nello Scenario 3), non aggiungiamo nulla 
            # e la regola di STOP base rimarrà valida.
                
        return final_tags

class RuleEvaluator:
    def __init__(self, rules: List[dict]):
        self.rules = sorted(rules, key=lambda x: x['priority'], reverse=True)

    def decide(self, active_tags: Set[str]) -> Tuple[str, bool, str]:
        for rule in self.rules:
            if set(rule.get('must_have', [])).issubset(active_tags) and set(rule.get('must_not_have', [])).isdisjoint(active_tags):
                return rule['action'], rule.get('needs_review', False), rule['reason']
        return "GO", False, "Nessun vincolo bloccante rilevato."

# =================================================================
# 5. ENDPOINT FASTAPI
# =================================================================
fusion_engine = SensorFusionEngine()
rule_evaluator = RuleEvaluator(TRAFFIC_RULES)

@app.post("/api/evaluate", response_model=ActionOutput)
def evaluate_scenario(scenario: ScenarioInput):
    try:
        conf_tags, ambig_tags, total_conf, ext_times = fusion_engine.fuse(scenario.sensori)
        
        # Fallback 1: Blackout Totale (No sensori attivi)
        if total_conf == 0:
            return ActionOutput(
                id_scenario=scenario.id_scenario, action="STOP", needs_review=True, 
                confidence=0.0, reason="Blackout totale sensori. Frenata di emergenza."
            )

        # Fallback 2: Margin of Doubt (Sensori in conflitto insanabile)
        if ambig_tags:
            return ActionOutput(
                id_scenario=scenario.id_scenario, action="STOP", needs_review=True, 
                confidence=total_conf, reason=f"Conflitto tra sensori sul concetto: [{', '.join(ambig_tags)}]. Richiesto operatore."
            )

        # Valutazione Standard
        final_tags = ContextEvaluator.evaluate(conf_tags, ext_times, scenario.orario_rilevamento, scenario.giorno_settimana)
        action, needs_review, reason = rule_evaluator.decide(final_tags)
        
        if "FUORI_RESTRIZIONE" in final_tags and action == "GO":
            reason += f" (Orario rilevato: {ext_times.get('start')}-{ext_times.get('end')})"

        return ActionOutput(
            id_scenario=scenario.id_scenario, 
            action=action, 
            needs_review=needs_review, 
            confidence=total_conf, 
            reason=reason
        )

    except Exception as e:
        # Fallback 3: Eccezione del codice Python
        return ActionOutput(
            id_scenario=scenario.id_scenario, action="STOP", needs_review=True, 
            confidence=0.0, reason="Frenata automatica di sicurezza per errore interno del software."
        )