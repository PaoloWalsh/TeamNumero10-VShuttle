# Hackathon Pitch & Build
## Progetto: V-Shuttle

---

# 1. Contesto

Il cliente della simulazione è **Hastega**, una software house con sede a Lucca in forte espansione.

Hastega ha recentemente acquisito una grande commessa da un cliente DeepTech:

**Waymo LCC**

Waymo gestisce flotte di **navette autonome di livello 4**.

Il volume del progetto supera la capacità interna di sviluppo di Hastega.

Per questo motivo l'azienda vuole selezionare **un team esterno di sviluppo** capace di:

- analizzare un problema reale
- progettare un sistema robusto
- costruire una dashboard utilizzabile in condizioni critiche
- lavorare sotto pressione

---

# 2. Il Problema

Le navette **V-Shuttle** operano nei centri storici toscani.

Questi ambienti sono complessi perché includono:

- Zone a Traffico Limitato (ZTL)
- strade strette
- segnaletica rovinata o difficile da leggere

Il software di guida autonoma è molto sicuro, ma ha un problema:

> è troppo conservativo.

Quando incontra cartelli ambigui o difficili da interpretare:

- il sistema frena
- la navetta si blocca
- i passeggeri percepiscono una frenata improvvisa

Questo fenomeno è chiamato:

**Phantom Braking**

---

# 3. Safety Driver

Per legge, a bordo della navetta è presente un **Safety Driver**.

Lo chiameremo **Marco**.

Marco:

- non guida il veicolo
- supervisiona il sistema autonomo
- può intervenire manualmente

Davanti a Marco c'è un **tablet da 12 pollici**.

Attualmente il tablet mostra solo:

- log tecnici
- codici di errore
- stringhe incomprensibili

Marco non riesce a capire:

- perché il veicolo ha frenato
- cosa sta succedendo
- se deve intervenire

---

# 4. Obiettivo del Progetto

Il cliente chiede di sviluppare due componenti:

1. **Parser Semantico**
2. **Dashboard Touch Live**

Il parser interpreta i cartelli.

La dashboard mostra la decisione al Safety Driver.

---

# 5. Sensori Disponibili

La navetta dispone di **tre sensori principali**.

### Camera Frontale
- molto affidabile

### Camera Laterale
- affidabilità media

### V2I Receiver
- comunica con infrastrutture
- può essere **offline**

---

# 6. Problema OCR

I sensori leggono lo stesso cartello ma possono restituire risultati diversi.

Esempio:
DIVIETO
D1V1ET0
DIVIETO DI ACCESSO


Queste differenze sono causate da:

- errori OCR
- cartelli deteriorati
- angoli di ripresa diversi

Il sistema deve **fondere queste informazioni**.

---

# 7. Struttura del Dataset JSON

Gli scenari sono forniti in formato JSON.

Ogni scenario contiene:

- id dello scenario
- letture dei sensori
- confidenza di ogni sensore
- orario della rilevazione
- giorno della settimana

---

## Esempio JSON

```json
{
  "id_scenario": 70,
  "sensori": {
    "camera_frontale": {
      "testo": "ZTL",
      "confidenza": 0.99
    },
    "camera_laterale": {
      "testo": "ZTL",
      "confidenza": 0.98
    },
    "V2I_receiver": {
      "testo": "ZTL",
      "confidenza": 0.97
    }
  }`
  "orario_rilevamento": "09:25",
  "giorno_settimana": "Venerdì"
}
```