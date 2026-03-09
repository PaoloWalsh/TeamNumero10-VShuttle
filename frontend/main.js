/**
 * V-SHUTTLE — Safety Driver Interface
 * main.js — SimulationController
 *
 * Architecture:
 *   SimulationController  → owns all state, prevents race conditions
 *   UIRenderer            → stateless DOM update functions
 *   ClockTicker           → live clock update loop
 */

/* ══════════════════════════════════════════════════
   CONSTANTS
══════════════════════════════════════════════════ */
const API_ENDPOINT = 'http://127.0.0.1:8000/api/evaluate';
const LOOP_INTERVAL_MS = 10000;   // 4 seconds between scenarios
const OVERRIDE_TIMEOUT = 5000;   // 2 seconds to human decision

/* ══════════════════════════════════════════════════
   SENSOR LABELS (human-friendly names)
══════════════════════════════════════════════════ */
const SENSOR_LABELS = {
    camera_frontale: 'VISIONE FRONTALE',
    camera_laterale: 'VISIONE LATERALE',
    V2I_receiver: 'INFRASTRUTTURA (V2I)',
    orario_rilevamento: 'ORA RILEVAMENTO',
    giorno_settimana: 'GIORNO'
};

const ACTION_LABELS = {
    GO: 'AVANTI',
    STOP: 'STOP',
    OVERRIDE_REQUIRED: 'RICHIESTA INTERVENTO',
};

const ACTION_DESCRIPTIONS = {
    GO: 'Il sistema ha valutato lo scenario in sicurezza. Proseguire il percorso.',
    STOP: 'Il sistema ha rilevato un rischio. La navetta rimane ferma.',
    OVERRIDE_REQUIRED: 'Il livello di confidenza è insufficiente. Richiesto intervento umano.',
};

/* ══════════════════════════════════════════════════
   SIMULATION CONTROLLER
══════════════════════════════════════════════════ */
class SimulationController {
    constructor() {
        this.scenarios = [];     // loaded dataset
        this.currentIndex = 0;      // next scenario pointer
        this.isRunning = false;  // main loop flag

        // Timers — held as IDs for reliable cancellation
        this._loopTimerId = null;
        this._overrideTimerId = null;
        this._loopProgressTimerId = null;
        this._overrideProgressRAF = null;

        // Prevents stale async responses from a previous cycle taking effect
        this._cycleToken = 0;

        this._suggestedAction = null;

        this._bindDOM();
        this._startClock();
    }

    /* ── DOM REFERENCES ─────────────────────────── */
    _bindDOM() {
        this.fileInput = document.getElementById('fileInput');
        this.fileStatus = document.getElementById('fileStatus');
        this.fileLabel = document.querySelector('.file-label');
        this.btnStart = document.getElementById('btnStart');
        this.btnStop = document.getElementById('btnStop');
        this.btnOverride = document.getElementById('btnOverride');
        this.btnConferma = document.getElementById('btnConferma');
        this.loopInfo = document.getElementById('loopInfo');
        this.loopTimerFill = document.getElementById('loopTimerFill');
        this.logEntries = document.getElementById('logEntries');
        this.scenarioCounter = document.getElementById('scenarioCounter');
        this.sensorGrid = document.getElementById('sensorGrid');
        this.historyList = document.getElementById('historyList');
        this.overridePanel = document.getElementById('overridePanel');
        this.decisionIdle = document.getElementById('decisionIdle');
        this.decisionCard = document.getElementById('decisionCard');
        this.decisionLabel = document.getElementById('decisionLabel');
        this.decisionAction = document.getElementById('decisionAction');
        this.actionText = document.getElementById('actionText');
        this.decisionDesc = document.getElementById('decisionDescription');
        this.confidenceFill = document.getElementById('confidenceBarFill');
        this.confidenceValue = document.getElementById('confidenceValue');
        this.countdownNumber = document.getElementById('countdownNumber');
        this.countdownFill = document.getElementById('countdownBarFill');
        this.countdownSection = document.getElementById('countdownSection');
        this.overrideFallbackText = document.getElementById('overrideFallbackText');

        // Event listeners
        this.fileInput.addEventListener('change', (e) => this._onFileLoad(e));
        this.btnStart.addEventListener('click', () => this._startLoop());
        this.btnStop.addEventListener('click', () => this._stopSimulation());
        this.btnOverride.addEventListener('click', () => this._onHumanDecision('OVERRIDE'));
        this.btnConferma.addEventListener('click', () => this._onHumanDecision('CONFERMA'));
    }

    /* ── CLOCK ──────────────────────────────────── */
    _startClock() {
        const el = document.getElementById('clock');
        const tick = () => {
            const now = new Date();
            el.textContent = now.toLocaleTimeString('it-IT');
        };
        tick();
        setInterval(tick, 1000);
    }

    /* ── FILE LOADING ───────────────────────────── */
    _onFileLoad(event) {
        const file = event.target.files[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = (e) => {
            try {
                const data = JSON.parse(e.target.result);
                if (!Array.isArray(data) || data.length === 0) {
                    throw new Error('Il file deve contenere un array di scenari non vuoto.');
                }
                this.scenarios = data;
                this.currentIndex = 0;

                this.fileStatus.textContent = `${data.length} scenari caricati`;
                this.fileLabel.classList.add('loaded');
                this.fileLabel.querySelector('.file-icon').textContent = '✅';
                this.btnStart.disabled = false;

                this._updateCounter();
                this._addLog(`Dataset caricato: ${data.length} scenari`, 'info');
                this._setSystemStatus('idle', 'DATASET PRONTO');

            } catch (err) {
                this.fileStatus.textContent = 'Errore nel file — riprova';
                this.fileLabel.classList.remove('loaded');
                this._addLog(`File non valido`, 'stop');
            }
        };
        reader.readAsText(file);
    }

    /* ── LOOP CONTROL ───────────────────────────── */
    _startLoop() {
        if (this.isRunning || this.scenarios.length === 0) return;
        if (this.currentIndex >= this.scenarios.length) {
            this.currentIndex = 0; // restart from beginning
        }
        this.isRunning = true;
        this._setUIRunning(true);
        this._addLog('Simulazione avviata', 'info');
        this._setSystemStatus('running', 'SIMULAZIONE ATTIVA');
        this._runNextScenario();
    }

    _stopSimulation() {
        this._cancelAllTimers();
        this.isRunning = false;
        this._cycleToken++;  // invalidate any in-flight fetch
        this._setUIRunning(false);
        this._showOverridePanelMode(null); // era: this._showOverridePanel(false)        this._addLog('Simulazione arrestata dal driver', 'stop');
        this._setSystemStatus('idle', 'SIMULAZIONE ARRESTATA');
    }

    /* ── SCENARIO EXECUTION ─────────────────────── */
    async _runNextScenario() {
        if (!this.isRunning) return;

        if (this.currentIndex >= this.scenarios.length) {
            this._addLog('Tutti gli scenari completati', 'info');
            this._setSystemStatus('idle', 'MISSIONE COMPLETATA');
            this._setUIRunning(false);
            this.isRunning = false;
            return;
        }

        const scenario = this.scenarios[this.currentIndex];
        const myToken = ++this._cycleToken;

        this._updateCounter();
        this._renderSensorData(scenario);
        this._showDecisionProcessing();
        this._addLog(`Scenario ${this.currentIndex + 1} inviato al sistema`, 'info');

        try {
            const response = await this._postScenario(scenario);
            // Stale check: if a newer cycle started, discard this response
            if (myToken !== this._cycleToken) return;
            // const response = {};
            // response.action = 'OVERRIDE_REQUIRED';
            // response.suggested_action = 'STOP';   // ← cambia in 'STOP' per testare l'altro caso
            // response.description = 'Confidenza insufficiente';
            // response.confidence = 35;
            await this._handleResponse(response);

        } catch (err) {
            if (myToken !== this._cycleToken) return;
            // Network / parsing error → treat as STOP for safety
            this._applyDecision({ action: 'STOP', confidence: 0, description: 'Errore di comunicazione con il sistema.' });
            this._addLog('Nessuna risposta dal backend — STOP di sicurezza', 'stop');
            this.currentIndex++;
            this._scheduleNextLoop();
        }
    }

    async _postScenario(scenario) {
        const res = await fetch(API_ENDPOINT, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(scenario),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
    }

    /* ── RESPONSE HANDLING ──────────────────────── */
    async _handleResponse(data) {
        console.log(data);
        const baseAction = (data.action || '').toUpperCase();
        const description = data.reason ?? data.description;
        const confidence = (data.confidence ?? 0) * 100;

        if (data.needs_review) {
            // Backend delegates decision to the driver; baseAction is the suggestion
            this._suggestedAction = baseAction || 'STOP';
            this._applyDecision({
                action: 'OVERRIDE_REQUIRED',
                confidence: confidence / 10,
                description: description ?? ACTION_DESCRIPTIONS['OVERRIDE_REQUIRED'],
            });
            this._addLog('Override richiesto — attesa decisione driver', 'override');
            this._updateConfermaButton(this._suggestedAction);
            this._startOverrideCountdown();
            return;
        }

        switch (baseAction) {
            case 'GO':
            case 'STOP':
                this._applyDecision({
                    action: baseAction,
                    confidence,
                    description: description ?? ACTION_DESCRIPTIONS[baseAction],
                });
                this._addLog(`Decisione: ${ACTION_LABELS[baseAction] || baseAction}`, baseAction === 'GO' ? 'go' : 'stop');
                this.currentIndex++;
                this._scheduleNextLoop();
                break;

            default:
                // Unknown response → STOP for safety
                this._applyDecision({ action: 'STOP', confidence: 0, description: 'Risposta non riconosciuta dal sistema.' });
                this.currentIndex++;
                this._scheduleNextLoop();
        }
    }

    /* ── DECISION UI ────────────────────────────── */
    _showDecisionProcessing() {
        this.decisionIdle.classList.add('hidden');
        this._showOverridePanelMode(null); // era: this.overridePanel.classList.add('hidden')
        this.decisionCard.classList.remove('hidden');

        this.decisionLabel.textContent = 'ELABORAZIONE IN CORSO';
        this.decisionAction.className = 'decision-action state-processing';
        this.actionText.textContent = '...';
        this.decisionDesc.textContent = 'Analisi del sistema in corso…';
        this.confidenceFill.style.width = '0%';
        this.confidenceValue.textContent = '—';
    }

    _applyDecision({ action, confidence, description }) {
        const isOverride = action === 'OVERRIDE_REQUIRED';

        // Show card with result
        this.decisionIdle.classList.add('hidden');
        this.decisionCard.classList.remove('hidden');

        this.decisionLabel.textContent = 'DECISIONE SISTEMA';

        const stateClass = action === 'GO' ? 'state-go' : action === 'STOP' ? 'state-stop' : 'state-override';
        this.decisionAction.className = `decision-action ${stateClass}`;
        this.actionText.textContent = ACTION_LABELS[action] || action;
        this.decisionDesc.textContent = description || ACTION_DESCRIPTIONS[action] || '';

        // Confidence bar
        const pct = Math.min(100, Math.max(0, confidence));
        this.confidenceFill.style.width = `${pct}%`;
        this.confidenceValue.textContent = `${Math.round(pct)}%`;

        // Confidence bar color by level
        if (pct >= 70) {
            this.confidenceFill.style.background = 'linear-gradient(90deg, #004d29, var(--go-primary))';
        } else if (pct >= 40) {
            this.confidenceFill.style.background = 'linear-gradient(90deg, #5a3c00, var(--override-primary))';
        } else {
            this.confidenceFill.style.background = 'linear-gradient(90deg, #5a0010, var(--stop-primary))';
        }

        // System status
        if (action === 'GO') {
            this._setSystemStatus('go', 'VIA LIBERA');
            this._showOverridePanelMode('manual');
        } else if (action === 'STOP') {
            this._setSystemStatus('stop', 'STOP — VEICOLO FERMO');
            this._showOverridePanelMode('manual');
        } else if (isOverride) {
            this._setSystemStatus('override', 'INTERVENTO RICHIESTO');
            this._showOverridePanelMode('full');
        }
    }

    /* ── OVERRIDE COUNTDOWN ─────────────────────── */
    _startOverrideCountdown() {
        const duration = OVERRIDE_TIMEOUT; // 2000ms
        const start = performance.now();

        this.countdownNumber.textContent = '2';
        this.countdownFill.style.width = '100%';
        this.countdownFill.style.transition = 'none';

        // Force repaint before animating
        requestAnimationFrame(() => {
            this.countdownFill.style.transition = `width ${duration}ms linear`;
            this.countdownFill.style.width = '0%';
        });

        // Update digit display
        const interval = setInterval(() => {
            const elapsed = performance.now() - start;
            const remaining = Math.max(0, Math.ceil((duration - elapsed) / 1000));
            this.countdownNumber.textContent = remaining.toString();
        }, 100);

        // Fallback fire
        this._overrideTimerId = setTimeout(() => {
            clearInterval(interval);
            if (this.isRunning) {
                this._onOverrideTimeout();
            }
        }, duration);

        // Store interval for cleanup
        this._overrideIntervalId = interval;
    }

    _onOverrideTimeout() {
        this._cancelOverrideTimer();
        this._showOverridePanelMode(null);

        // Safety fallback: enforce STOP
        this.decisionAction.className = 'decision-action state-stop';
        this.actionText.textContent = ACTION_LABELS['STOP'];
        this.decisionDesc.textContent = 'Nessuna risposta del driver — STOP automatico applicato.';
        this._setSystemStatus('stop', 'STOP AUTOMATICO');

        this._addLog('Timeout scaduto — STOP automatico', 'stop');

        this.currentIndex++;
        this._scheduleNextLoop();
    }

    _onHumanDecision(choice) {
        if (!this.isRunning) return;
        this._cancelAllTimers();
        this._showOverridePanelMode(null);

        if (choice === 'OVERRIDE') {
            this.decisionAction.className = 'decision-action state-stop';
            this.actionText.textContent = ACTION_LABELS['STOP'];
            this.decisionDesc.textContent = 'Override manuale del driver — controllo ceduto all\'operatore.';
            this._setSystemStatus('stop', 'OVERRIDE — CONTROLLO MANUALE');
            this._addLog('Driver: Override manuale applicato', 'override');
        } else {
            const confirmed = this._suggestedAction || 'STOP';
            const stateClass = confirmed === 'GO' ? 'state-go' : 'state-stop';
            this.decisionAction.className = `decision-action ${stateClass}`;
            this.actionText.textContent = ACTION_LABELS[confirmed] || confirmed;
            this.decisionDesc.textContent = `Suggerimento confermato dal driver: ${ACTION_LABELS[confirmed]}.`;
            this._setSystemStatus(confirmed === 'GO' ? 'go' : 'stop', `CONFERMATO — ${ACTION_LABELS[confirmed]}`);
            this._addLog(`Driver: Confermato suggerimento ${ACTION_LABELS[confirmed]}`, 'override');
        }

        this.currentIndex++;
        this._runNextScenario();  // entrambi avanzano immediatamente
    }

    /* ── LOOP SCHEDULING ────────────────────────── */
    _scheduleNextLoop() {
        if (!this.isRunning) return;

        // Animate progress bar over LOOP_INTERVAL_MS
        this.loopTimerFill.style.transition = 'none';
        this.loopTimerFill.style.width = '0%';

        requestAnimationFrame(() => {
            this.loopTimerFill.style.transition = `width ${LOOP_INTERVAL_MS}ms linear`;
            this.loopTimerFill.style.width = '100%';
        });

        this._loopTimerId = setTimeout(() => {
            this.loopTimerFill.style.width = '0%';
            this.loopTimerFill.style.transition = 'none';
            this._runNextScenario();
        }, LOOP_INTERVAL_MS);
    }

    /* ── TIMER CLEANUP ──────────────────────────── */
    _cancelAllTimers() {
        if (this._loopTimerId) { clearTimeout(this._loopTimerId); this._loopTimerId = null; }
        this._cancelOverrideTimer();
    }

    _cancelOverrideTimer() {
        if (this._overrideTimerId) { clearTimeout(this._overrideTimerId); this._overrideTimerId = null; }
        if (this._overrideIntervalId) { clearInterval(this._overrideIntervalId); this._overrideIntervalId = null; }
    }

    /* ── UI HELPERS ─────────────────────────────── */
    _setUIRunning(running) {
        this.btnStart.classList.toggle('hidden', running);
        this.btnStop.classList.toggle('hidden', !running);
        this.loopInfo.classList.toggle('hidden', !running);
        this.loopTimerFill.style.width = '0%';
        if (!running) {
            this.decisionCard.classList.add('hidden');
            this.decisionIdle.classList.remove('hidden');
        }
    }

    _showOverridePanelMode(mode) {
        // mode: 'full' (OVERRIDE_REQUIRED, con countdown + entrambi i pulsanti)
        //       'manual' (GO/STOP, solo pulsante OVERRIDE)
        //       null (nasconde tutto)
        const show = mode !== null;
        this.overridePanel.classList.toggle('hidden', !show);
        const isFull = mode === 'full';
        this.btnConferma.classList.toggle('hidden', !isFull);
        const seconds = Math.round(OVERRIDE_TIMEOUT / 1000);
        this.countdownNumber.textContent = seconds.toString();
        if (this.countdownSection) this.countdownSection.classList.toggle('hidden', !isFull);
        if (this.overrideFallbackText) {
            this.overrideFallbackText.classList.toggle('hidden', !isFull); // ← aggiunta
            this.overrideFallbackText.textContent = seconds; // ← aggiunta
        }
    }

    _setSystemStatus(state, label) {
        const el = document.getElementById('sysStatus');
        const dot = document.getElementById('statusDot');
        const lbl = document.getElementById('statusLabel');

        el.className = `sys-status state-${state}`;
        lbl.textContent = label;
    }

    _updateCounter() {
        this.scenarioCounter.textContent = `${Math.min(this.currentIndex + 1, this.scenarios.length)} / ${this.scenarios.length}`;
    }

    _updateConfermaButton(suggestion) {
        if (!this.btnConferma) return;
        const isGo = suggestion === 'GO';
        this.btnConferma.className = `btn-override ${isGo ? 'btn-override-confirm-go' : 'btn-override-confirm-stop'}`;
        const icon = this.btnConferma.querySelector('.ovr-icon');
        const text = this.btnConferma.querySelector('.ovr-text');
        const sub = this.btnConferma.querySelector('.ovr-sub');
        if (icon) icon.textContent = isGo ? '✅' : '🛑';
        if (text) text.textContent = `CONFERMA ${ACTION_LABELS[suggestion] || suggestion}`;
        if (sub) sub.textContent = isGo ? 'Procedi come suggerito' : 'Fermati come suggerito';
    }

    /* ── SENSOR RENDERING ───────────────────────── */
    _renderSensorData(scenario) {
        this.sensorGrid.innerHTML = '';

        // Combiniamo i dati dei sensori nidificati con i metadati dello scenario
        const displayData = {
            ...scenario.sensori,
            orario_rilevamento: scenario.orario_rilevamento,
            giorno_settimana: scenario.giorno_settimana
        };

        Object.entries(displayData).forEach(([key, data]) => {
            const label = SENSOR_LABELS[key] || key.toUpperCase();

            // Estraiamo il testo "fuso" finale (evitiamo JSON grezzo)
            let displayValue = "DATO ASSENTE";
            let confidence = null;

            if (data && typeof data === 'object') {
                displayValue = data.testo || "NESSUN SEGNALE";
                confidence = data.confidenza;
            } else {
                displayValue = data || "N/D";
            }

            const card = document.createElement('div');
            card.className = `sensor-card ${confidence < 0.7 && confidence !== null ? 'sensor-warning' : ''}`;

            card.innerHTML = `
            <span class="sensor-name">${label}</span>
            <span class="sensor-value">${displayValue}</span>
            ${confidence !== null ? `<small>Attendibilità: ${Math.round(confidence * 100)}%</small>` : ''}
        `;
            this.sensorGrid.appendChild(card);
        });
    }

    /* ── LOG ────────────────────────────────────── */
    _addLog(message, type = 'info') {
        // Clear placeholder
        const placeholder = this.logEntries.querySelector('.log-idle');
        if (placeholder) placeholder.remove();

        const time = new Date().toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        const entry = document.createElement('div');
        entry.className = `log-entry log-${type}`;
        entry.textContent = `${time} — ${message}`;

        this.logEntries.prepend(entry);

        // Keep max 20 entries
        while (this.logEntries.children.length > 20) {
            this.logEntries.removeChild(this.logEntries.lastChild);
        }
    }

}

/* ══════════════════════════════════════════════════
   BOOT
══════════════════════════════════════════════════ */
document.addEventListener('DOMContentLoaded', () => {
    window.sim = new SimulationController();
});