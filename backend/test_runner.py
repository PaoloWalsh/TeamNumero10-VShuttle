import json
import requests

# 1. Carica il file JSON con tutti gli scenari
try:
    with open('VShuttle-input.json', 'r', encoding='utf-8') as f:
        scenarios = json.load(f)
except FileNotFoundError:
    print("Errore: File VShuttle-input.json non trovato!")
    exit()

url = "http://127.0.0.1:8000/api/evaluate"

print(f"🚀 Inizio stress test su {len(scenarios)} scenari...\n")
print("-" * 60)

error_count = 0
review_count = 0

# 2. Cicla attraverso ogni scenario e lo invia al backend
for scenario in scenarios:
    try:
        response = requests.post(url, json=scenario)
        
        # Se il server ha risposto correttamente (HTTP 200 OK)
        if response.status_code == 200:
            result = response.json()
            azione = result['action']
            
            # Formattazione visiva per il terminale
            icona = "🟢" if azione == "GO" else "🔴" if azione == "STOP" else "🟡"
            if azione == "REVIEW": review_count += 1
            
            print(f"{icona} Scenario {result['id_scenario']:<4} | Azione: {azione:<6} | Confidenza: {result['confidence']:.2f}")
            print(f"   Motivo: {result['reason']}")
            
        else:
            print(f"❌ Errore Backend su Scenario {scenario['id_scenario']}: Status {response.status_code}")
            error_count += 1
            
    except requests.exceptions.ConnectionError:
        print("❌ Errore di connessione: Il server FastAPI è acceso? (Usa uvicorn main:app)")
        break
        
    print("-" * 60)

# 3. Report finale
print(f"\n✅ Test Completato!")
print(f"Scenari totali: {len(scenarios)}")
print(f"Interventi umani richiesti (REVIEW): {review_count}")
print(f"Errori di sistema (Crash): {error_count}")

if error_count == 0:
    print("🏆 OTTIMO LAVORO! Il backend è solido e non è mai andato in crash.")