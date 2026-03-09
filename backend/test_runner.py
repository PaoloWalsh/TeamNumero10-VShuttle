import json
import requests

# Configurazione
BACKEND_URL = "http://127.0.0.1:8000/api/evaluate"
INPUT_DATA = "VShuttle-input.json"
EXPECTED_DATA = "VShuttle-expected.json"

def run_comprehensive_test():
    try:
        with open(INPUT_DATA, 'r', encoding='utf-8') as f:
            scenarios = json.load(f)
        with open(EXPECTED_DATA, 'r', encoding='utf-8') as f:
            expected_results = json.load(f)
    except Exception as e:
        print(f"❌ Errore caricamento file: {e}")
        return

    print(f"🚀 V-SHUTTLE QA RUNNER: Valutazione di {len(scenarios)} scenari")
    print("-" * 80)

    passed, failed, errors = 0, 0, 0

    for scenario in scenarios:
        sid = str(scenario['id_scenario'])
        try:
            response = requests.post(BACKEND_URL, json=scenario, timeout=2)
            if response.status_code == 200:
                actual = response.json()
                exp = expected_results.get(sid)
                
                # Validazione
                if exp:
                    match = (actual['action'] == exp['action'] and 
                             actual['needs_review'] == exp['needs_review'])
                    
                    if match:
                        passed += 1
                        status = "✅ PASS"
                    else:
                        failed += 1
                        status = f"❌ FAIL (Atteso {exp['action']}/Rev:{exp['needs_review']})"
                    
                    print(f"Scenario {sid:<4} | Result: {actual['action']:<4} | Review: {str(actual['needs_review']):<5} | {status}")
                else:
                    print(f"Scenario {sid:<4} | ⚠️  Mancante nel file expected")
            else:
                print(f"Scenario {sid:<4} | ❌ Errore Server (Status {response.status_code})")
                errors += 1
        except Exception:
            print(f"Scenario {sid:<4} | ❌ Connessione fallita")
            errors += 1

    print("-" * 80)
    print(f"📊 REPORT FINALE:")
    print(f"✅ Passati: {passed}")
    print(f"❌ Falliti: {failed}")
    print(f"⚠️  Errori Tecnici: {errors}")
    
    if failed == 0 and errors == 0:
        print("\n🏆 BACKEND VALIDATO AL 100%! Pronto per il Test Segreto di Paolo.")

if __name__ == "__main__":
    run_comprehensive_test()