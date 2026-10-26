// Overlay de reproducción de AltR: port a Windows del overlay Alt+R de Linux
// (Quickshell, tts-status/shell.qml). Misma estética "Fantasma": una cápsula de vidrio
// (#ec0e0c12 por defecto), el color vive sólo en la onda y en la palabra que suena
// (verde #3ddc84 -> #7dffb0), todo lo que se toca mide 32 px, y el karaoke (3 líneas: anterior,
// actual y siguiente, con la palabra actual en una píldora que se desliza).
//
// Diferencias con Linux: no hay chip de velocidad (la reproducción de Windows no cambia la
// velocidad; se elige en [tts] speed) ni teclado (la ventana nunca toma el foco).
//
// La ventana la maneja altr/overlay.py: le pone estas propiedades (fase, textos, duraciones,
// posición, picos) cada 100 ms y recibe de vuelta, por el objeto `bridge`, pausa / cortar / saltar
// y el rectángulo de la cápsula (la máscara que deja pasar los clics por el resto).

import QtQuick

Item {
    id: root

    // ---- lo que pone Python ----
    property string phase: "idle"     // idle | preparing | playing | paused | stalled | error | done
    property string sid: ""           // identidad de la lectura (cambia con cada lectura nueva)
    property var texts: []            // texto mostrado, por trozo
    property var durs: []             // por trozo: -1 sin generar, 0 sin audio, si no segundos
    property real pos: 0              // tiempo global en la lectura
    property bool complete: false     // ya se generaron todos los trozos
    property var peaks: []            // 18 valores 0..1
    property string errText: ""
    // ---- de [overlay] en el config ----
    property int cardW: 704
    property int kfont: 16
    property real bgAlpha: 0.925
    property bool atTop: false

    // ---- geometría y paleta (igual que Linux) ----
    readonly property int hueco: 16          // aire entre el borde de la pantalla y la cápsula
    readonly property int btn: 32            // todo lo que se toca mide 32
    readonly property int nbars: 18          // valores de la onda que manda Python
    readonly property int wbars: 56          // barras que se dibujan (interpoladas)
    readonly property int barGap: 2
    readonly property int waveH: 24
    readonly property int textW: cardW - 32
    readonly property int prepErrSecs: 45    // armando más que esto = error
    readonly property color verde0: "#3ddc84"
    readonly property color verde1: "#7dffb0"
    readonly property color critico: "#f26d6d"
    readonly property color txt: "#f2f4f7"
    readonly property color txtMut: "#a3a6ad"
    readonly property color txtDis: "#5d5f66"
    readonly property color tile: "#18ffffff"
    readonly property color tileHover: "#29ffffff"
    readonly property color fondo: Qt.rgba(14 / 255, 12 / 255, 18 / 255, bgAlpha)

    FontLoader { id: fReg; source: Qt.resolvedUrl("fonts/Inter-Regular.ttf") }
    FontLoader { id: fMed; source: Qt.resolvedUrl("fonts/Inter-Medium.ttf") }
    readonly property string fuente: fReg.status === FontLoader.Ready ? fReg.name : "Segoe UI"
    readonly property string fuenteMed: fMed.status === FontLoader.Ready ? fMed.name : "Segoe UI Semibold"

    // alto de una línea del karaoke: el natural de la fuente (natH, el que mide el TextEdit
    // oculto) y el que se dibuja (lineH, con más aire entre líneas)
    TextMetrics { id: lineMetrics; text: "Ágy"; font.family: root.fuente; font.pixelSize: root.kfont }
    readonly property int natH: Math.max(16, Math.ceil(lineMetrics.height))
    readonly property int lineH: Math.ceil(natH * 1.3)
    // alto FINAL de la cápsula según el estado (la animación va aparte, en `height`)
    readonly property int pillTargetH: hasText ? 80 + 3 * lineH : 44

    // la ventana mide lo máximo que puede ocupar: cápsula grande + hueco + etiqueta del seek
    width: cardW
    height: hueco + 80 + 3 * lineH + 40

    // ---- estado derivado de la fase ----
    readonly property bool preparing: phase === "preparing"
    readonly property bool playing: phase === "playing" || phase === "paused" || phase === "stalled"
    readonly property bool paused: phase === "paused"
    readonly property bool stalled: phase === "stalled"
    readonly property bool errored: phase === "error" || (preparing && prepSecs >= prepErrSecs)
    readonly property bool showing: preparing || playing || phase === "error"
    // la interfaz de reproducción sigue en pantalla mientras la tarjeta se desvanece
    // (exitHold), así no se vacía ni se encoge antes de irse
    property bool exitHold: false
    readonly property bool playUi: playing || exitHold
    readonly property bool hasText: playUi && lecWords > 0
    // Python oculta la ventana cuando esto es false
    readonly property bool uiActive: showing || exitHold || appear > 0.01

    property int prepSecs: 0
    property real globalPos: 0
    // `pos` llega cada 100 ms; visPos lo extrapola entre muestras con el reloj local para que la
    // palabra marcada avance a su hora y no a saltos
    property real visPos: 0
    property real posBase: 0
    property double posStamp: 0
    property bool seeking: false
    property real seekTarget: 0
    property real reveal: 0           // 0->1: la onda crece desde el centro al arrancar

    onPosChanged: {
        if (seeking) return
        globalPos = pos
        posBase = pos; posStamp = Date.now()
        if (Math.abs(pos - visPos) > 0.6) visPos = pos
    }
    Timer {
        interval: 33; repeat: true
        running: root.hasText && root.phase === "playing" && !root.seeking
        onTriggered: {
            const v = root.posBase + Math.min(0.3, (Date.now() - root.posStamp) / 1000)
            if (v > root.visPos) root.visPos = v
        }
    }

    // ---- lectura -> palabras (karaoke) ----
    property string lecFlat: ""       // todo el texto, palabras separadas por un espacio
    property var lecWs: []            // inicio de cada palabra dentro de lecFlat
    property var lecWe: []            // fin
    property var lecCw0: []           // índice de la primera palabra de cada trozo
    property var lecDurs: []          // duración por trozo (null = sin generar)
    readonly property int lecWords: lecWs.length

    function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)) }
    function fmt(s) {
        if (!s || s < 0 || isNaN(s)) s = 0
        const m = Math.floor(s / 60), r = Math.floor(s % 60)
        return m + ":" + (r < 10 ? "0" + r : r)
    }
    function clearLectura() {
        lecFlat = ""; lecWs = []; lecWe = []; lecCw0 = []
    }
    function buildLectura() {
        let flat = "", ws = [], we = [], cw0 = []
        for (let k = 0; k < texts.length; k++) {
            const words = String(texts[k] || "").split(/\s+/).filter(w => w.length > 0)
            cw0.push(ws.length)
            for (let i = 0; i < words.length; i++) {
                if (flat.length > 0) flat += " "
                ws.push(flat.length)
                flat += words[i]
                we.push(flat.length)
            }
        }
        lecFlat = flat; lecWs = ws; lecWe = we; lecCw0 = cw0
    }
    onTextsChanged: buildLectura()
    onDursChanged: lecDurs = durs.map(d => (d === undefined || d === null || d < 0) ? null : d)

    readonly property real totalDur: {
        let t = 0
        for (let i = 0; i < lecDurs.length; i++) if (lecDurs[i] !== null) t += lecDurs[i]
        return t
    }
    readonly property bool ready: playing && totalDur > 0
    readonly property real frac: totalDur > 0 ? clamp(globalPos / totalDur, 0, 1) : 0
    readonly property int curBar: Math.min(wbars - 1, Math.floor(frac * wbars))

    // palabra que suena en el instante t: trozo por suma acumulada de duraciones, y dentro del
    // trozo proporcional a los caracteres. Un trozo con duración 0 (sin audio) ocupa 0 s: se
    // salta sin frenar la cuenta. Pasado lo generado (null) queda en la última palabra del
    // último trozo con audio.
    function wordAt(t) {
        const n = lecDurs.length, nw = lecWs.length
        if (n === 0 || nw === 0) return -1
        let start = 0, k = -1
        for (let i = 0; i < n; i++) {
            const d = lecDurs[i]
            if (d === null) break
            if (d <= 0) continue
            k = i
            if (t < start + d) break
            start += d
        }
        if (k < 0) return 0
        const w0 = lecCw0[k], w1 = (k + 1 < n) ? lecCw0[k + 1] : nw
        const d = lecDurs[k]
        if (w1 <= w0) return Math.min(w0, nw - 1)
        const f = clamp((t - start) / d, 0, 1)
        let total = 0
        for (let i = w0; i < w1; i++) total += lecWe[i] - lecWs[i] + 1
        const goal = f * total
        let run = 0
        for (let i = w0; i < w1; i++) {
            run += lecWe[i] - lecWs[i] + 1
            if (goal < run) return i
        }
        return w1 - 1
    }
    // inverso de wordAt: instante en que EMPIEZA la palabra i, con el mismo mapeo. -1 si la
    // palabra no se puede ubicar: su trozo (o uno anterior) aún no se generó o no tiene audio.
    function wordStart(i) {
        const n = lecDurs.length, nw = lecWs.length
        if (i < 0 || i >= nw) return -1
        let k = 0
        while (k + 1 < n && lecCw0[k + 1] <= i) k++
        let start = 0
        for (let j = 0; j < k; j++) {
            if (lecDurs[j] === null) return -1
            start += lecDurs[j]
        }
        const d = lecDurs[k]
        if (d === null || d <= 0) return -1
        const w1 = (k + 1 < n) ? lecCw0[k + 1] : nw
        let total = 0, before = 0
        for (let j = lecCw0[k]; j < w1; j++) {
            const c = lecWe[j] - lecWs[j] + 1
            if (j < i) before += c
            total += c
        }
        return start + d * before / total
    }
    // Seek GLOBAL: el destino se muestra ya y Python se encarga de ubicarlo en su trozo.
    function seekGlobal(t) {
        if (totalDur <= 0) return
        t = clamp(t, 0, totalDur)
        seekTarget = t
        globalPos = t
    }
    // clic en una palabra del karaoke: saltar a su inicio. Un pelo adentro (20 ms) para que el
    // redondeo no la deje en el final de la palabra anterior.
    function seekWord(i) {
        const t = wordStart(i)
        if (t < 0 || !ready || t >= totalDur) return
        seekGlobal(t + 0.02)
        visPos = globalPos
        bridge.seek(globalPos)
    }

    // ---- onda: altura de cada barra ----
    function peakAt(i) {
        if (peaks.length !== nbars) return 0.35
        const x = i / (wbars - 1) * (nbars - 1)
        const a = Math.floor(x), b = Math.min(nbars - 1, a + 1)
        return peaks[a] * (1 - (x - a)) + peaks[b] * (x - a)
    }
    function barH(i) {
        const d = Math.abs(i - (wbars - 1) / 2) / ((wbars - 1) / 2)
        const f = clamp((reveal - d * 0.35) / 0.65, 0, 1)
        return (4 + peakAt(i) * (waveH - 4)) * f
    }
    function barColor(i) {
        if (i < curBar) {
            const t = i / Math.max(1, wbars - 1)
            return Qt.rgba(verde0.r + (verde1.r - verde0.r) * t,
                           verde0.g + (verde1.g - verde0.g) * t,
                           verde0.b + (verde1.b - verde0.b) * t, 1)
        }
        if (i === curBar) return "#eafff2"
        return "#38ffffff"
    }
    NumberAnimation on reveal {
        id: revealAnim
        running: false
        from: 0; to: 1; duration: 180; easing.type: Easing.OutCubic
    }
    onPlayingChanged: if (playing) revealAnim.restart()

    function resetVals() {
        peaks = []; reveal = 0; globalPos = 0; pos = 0; visPos = 0; posBase = 0
        seeking = false; prepSecs = 0; lecDurs = []
    }
    // lectura nueva: lo que quedaba de la anterior se limpia ya
    onSidChanged: {
        exitTimer.stop(); exitHold = false
        resetVals(); clearLectura()
        texts = []; durs = []   // así Python puede mandar los nuevos aunque sean iguales
        if (playing) revealAnim.restart()
    }

    // ---- entrada/salida de la tarjeta: 0 -> 1, una sola animación (opacidad, escala, posición) ----
    property real appear: 0
    NumberAnimation { id: appearAnim; target: root; property: "appear" }
    onShowingChanged: {
        appearAnim.stop()
        appearAnim.to = showing ? 1 : 0
        appearAnim.duration = showing ? 300 : 200
        appearAnim.easing.type = showing ? Easing.OutCubic : Easing.InCubic
        appearAnim.start()
        if (showing) {
            exitTimer.stop(); exitHold = false
        } else {
            exitHold = true
            exitTimer.restart()
        }
        updateMask()
    }
    Timer {
        id: exitTimer
        interval: 240
        onTriggered: { root.exitHold = false; root.resetVals(); root.clearLectura() }
    }
    // armando: tiempo transcurrido (para pasar a error)
    Timer {
        interval: 1000; repeat: true; running: root.preparing
        onTriggered: root.prepSecs++
    }
    onPreparingChanged: if (!preparing) prepSecs = 0

    // ---- máscara: sólo la cápsula captura clics, el resto de la ventana es transparente a ellos ----
    function updateMask() {
        if (showing || exitHold) bridge.setMask(Math.round(pill.x), Math.round(pill.y),
                                                Math.round(pill.width), Math.round(pill.height))
        else bridge.setMask(0, 0, 0, 0)
    }
    onExitHoldChanged: updateMask()

    // ---- piezas reutilizables ----
    // Íconos dibujados (viewBox 24, igual que los del boceto).
    component Glyph: Canvas {
        property string kind: "x"
        property color tint: root.txt
        width: 20; height: 20
        onTintChanged: requestPaint()
        onKindChanged: requestPaint()
        onPaint: {
            const c = getContext("2d")
            c.reset()
            c.scale(width / 24, height / 24)
            c.fillStyle = tint; c.strokeStyle = tint
            c.lineCap = "round"; c.lineJoin = "round"
            if (kind === "pause") {
                c.beginPath(); c.roundedRect(6.5, 5, 3.6, 14, 1.5, 1.5); c.fill()
                c.beginPath(); c.roundedRect(13.9, 5, 3.6, 14, 1.5, 1.5); c.fill()
            } else if (kind === "play") {
                c.beginPath()
                c.moveTo(8, 5.8); c.lineTo(8, 18.2)
                c.quadraticCurveTo(8, 19.3, 9, 18.7)
                c.lineTo(18.8, 12.9); c.quadraticCurveTo(19.6, 12, 18.8, 11.1)
                c.lineTo(9, 5.3); c.quadraticCurveTo(8, 4.7, 8, 5.8)
                c.closePath(); c.fill()
            } else if (kind === "x") {
                c.lineWidth = 2
                c.beginPath(); c.moveTo(7, 7); c.lineTo(17, 17); c.moveTo(17, 7); c.lineTo(7, 17); c.stroke()
            } else if (kind === "alert") {
                c.lineWidth = 2
                c.beginPath(); c.arc(12, 12, 8.5, 0, 2 * Math.PI); c.stroke()
                c.lineWidth = 2.2
                c.beginPath(); c.moveTo(12, 7.5); c.lineTo(12, 13); c.stroke()
                c.beginPath(); c.arc(12, 16.4, 1.3, 0, 2 * Math.PI); c.fill()
            }
        }
    }
    // Botón redondo de 32 px: "tiled" lleva fondo propio, el resto sólo se ilumina al pasar.
    component RoundBtn: Rectangle {
        id: rb
        property bool tiled: false
        property bool live: true
        property string glyph: "x"
        signal clicked()
        width: root.btn; height: root.btn; radius: root.btn / 2
        color: ma.containsMouse && live ? root.tileHover : (tiled ? root.tile : "transparent")
        opacity: live ? 1.0 : 0.45
        Behavior on color { ColorAnimation { duration: 100 } }
        Behavior on opacity { NumberAnimation { duration: 120 } }
        Glyph {
            anchors.centerIn: parent
            kind: rb.glyph
            tint: rb.tiled || ma.containsMouse ? root.txt : root.txtMut
        }
        MouseArea {
            id: ma; anchors.fill: parent; hoverEnabled: true
            enabled: rb.live
            cursorShape: Qt.PointingHandCursor
            onClicked: rb.clicked()
        }
    }

    // ---- la cápsula de vidrio ----
    Rectangle {
        id: pill
        x: 0
        y: root.atTop ? root.hueco - 14 * (1 - root.appear)
                      : root.height - height - (root.hueco - 14 * (1 - root.appear))
        opacity: root.appear
        visible: root.appear > 0.01
        scale: 0.94 + 0.06 * root.appear
        transformOrigin: root.atTop ? Item.Top : Item.Bottom

        width: root.cardW
        height: root.pillTargetH
        radius: root.hasText ? 22 : height / 2
        color: root.fondo
        // contorno de 1 px teñido; en error pasa a rojo crítico
        border.width: 1
        border.color: root.errored ? Qt.rgba(0.95, 0.43, 0.43, 0.6) : "#4dd5eadc"
        Behavior on height {
            NumberAnimation { duration: 280; easing.type: Easing.OutCubic }
        }
        Behavior on radius { NumberAnimation { duration: 280; easing.type: Easing.OutCubic } }
        Behavior on border.color { ColorAnimation { duration: 140 } }
        onXChanged: root.updateMask()
        onYChanged: root.updateMask()
        onWidthChanged: root.updateMask()
        onHeightChanged: root.updateMask()

        // brillo de arriba (el «borde de luz» del vidrio)
        Rectangle {
            anchors.fill: parent; anchors.margins: 1
            radius: parent.radius - 1
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#12f4f5f7" }
                GradientStop { position: 0.55; color: "#00f4f5f7" }
            }
        }
        Rectangle {
            y: 1; height: 1
            anchors.left: parent.left; anchors.right: parent.right
            anchors.leftMargin: parent.radius * 0.8; anchors.rightMargin: parent.radius * 0.8
            color: "#2effffff"
        }

        // ================== ARMANDO / ERROR ==================
        Item {
            id: prepRow
            anchors.fill: parent
            anchors.leftMargin: 14; anchors.rightMargin: 6
            visible: root.preparing || root.phase === "error"

            // rueda: pista + arco verde que gira (único movimiento continuo)
            Item {
                id: spin
                width: 20; height: 20
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                visible: !root.errored
                Canvas {
                    anchors.fill: parent
                    onPaint: {
                        const c = getContext("2d"); c.reset()
                        c.lineWidth = 2.4; c.lineCap = "round"
                        c.strokeStyle = "#29ffffff"
                        c.beginPath(); c.arc(10, 10, 8, 0, 2 * Math.PI); c.stroke()
                        c.strokeStyle = root.verde1
                        c.beginPath(); c.arc(10, 10, 8, -Math.PI / 2, 0); c.stroke()
                    }
                }
                RotationAnimator on rotation {
                    running: prepRow.visible && !root.errored
                    from: 0; to: 360; duration: 900; loops: Animation.Infinite
                }
            }
            Glyph {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                visible: root.errored
                kind: "alert"; tint: root.critico
            }
            Text {
                id: prepLbl
                anchors.left: parent.left; anchors.leftMargin: 28
                anchors.verticalCenter: parent.verticalCenter
                text: root.errored ? "No pude leer" : "Preparando"
                color: root.txt
                font.family: root.fuenteMed; font.pixelSize: 13
            }
            Text {
                anchors.left: prepLbl.right; anchors.leftMargin: 8
                anchors.right: prepX.left; anchors.rightMargin: 8
                anchors.verticalCenter: parent.verticalCenter
                elide: Text.ElideRight
                color: root.txtMut
                font.family: root.fuente; font.pixelSize: 12
                text: {
                    if (root.errored) return root.errText !== "" ? root.errText : "el motor de voz no respondió"
                    if (root.lecWords === 0) return ""
                    const head = root.lecFlat.length > 60 ? root.lecFlat.slice(0, 60) + "…" : root.lecFlat
                    return root.lecWords + " palabras · «" + head + "»"
                }
            }
            RoundBtn {
                id: prepX
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                glyph: "x"
                onClicked: bridge.stop()
            }
        }

        // ================== LEYENDO ==================
        // texto (karaoke): fuera de la fila de controles para que ésta no se mueva.
        // Todo el texto va en un solo bloque que se desliza (flow); encima, en capas
        // recortadas, la misma copia en tenue (lo ya leído) y en verde (la palabra
        // actual, dentro de la píldora). La píldora se desliza de palabra en palabra
        // y las capas la siguen, así el avance es un barrido y no un salto de color.
        Item {
            id: karaoke
            x: 16; y: 12
            width: root.textW
            height: 3 * root.lineH
            clip: true
            visible: opacity > 0.01
            opacity: root.hasText ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }

            // medidor oculto: misma fuente y ancho que el Text visible, para saber dónde
            // cae la palabra actual (un Text no expone positionToRectangle)
            TextEdit {
                id: meas
                visible: false
                width: root.textW
                readOnly: true
                wrapMode: TextEdit.Wrap
                font.family: root.fuente; font.pixelSize: root.kfont
                text: root.lecFlat
            }

            // palabra actual y su rectángulo [x, línea, ancho] en el medidor
            readonly property int cw: root.hasText ? root.wordAt(root.seeking ? root.seekTarget : root.visPos) : -1
            readonly property var wr: {
                // dependencias explícitas: positionToRectangle no notifica solo
                const _a = meas.text, _b = meas.width, _c = meas.contentHeight
                if (cw < 0 || meas.text !== root.lecFlat) return [0, 0, 0]
                const a = meas.positionToRectangle(root.lecWs[cw])
                const b = meas.positionToRectangle(root.lecWe[cw])
                const ln = Math.round(a.y / root.natH)
                return [a.x, ln, Math.round(b.y / root.natH) === ln ? b.x - a.x : meas.width - a.x]
            }
            readonly property int curLine: wr[1]

            // clic en una palabra = saltar a ella. hoverW: la palabra bajo el puntero si
            // se puede ubicar en el audio (trozo ya generado), si no -1 (sin mano ni resalte).
            function wordAtPoint(mx, my) {
                const _a = meas.text, _b = meas.width, _c = meas.contentHeight
                if (meas.text !== root.lecFlat || root.lecWords === 0) return -1
                // el texto visible usa filas de lineH y el medidor filas de natH: se pasa de una a otra
                const ln = Math.floor(my / root.lineH)
                if (ln < 0 || ln >= Math.round(meas.contentHeight / root.natH) || mx < 0 || mx > root.textW) return -1
                const p = meas.positionAt(mx, ln * root.natH + root.natH / 2)
                let lo = 0, hi = root.lecWords - 1
                while (lo < hi) {                      // última palabra con inicio <= p
                    const mid = (lo + hi + 1) >> 1
                    if (root.lecWs[mid] <= p) lo = mid; else hi = mid - 1
                }
                return lo
            }
            readonly property int hoverW: {
                if (!kma.containsMouse || !root.ready) return -1
                const w = wordAtPoint(kma.mouseX, kma.mouseY - flow.y)
                const t = w < 0 ? -1 : root.wordStart(w)
                return (t >= 0 && t < root.totalDur) ? w : -1
            }
            readonly property var hr: {
                const _a = meas.text, _b = meas.width, _c = meas.contentHeight
                if (hoverW < 0 || meas.text !== root.lecFlat) return [0, 0, 0]
                const a = meas.positionToRectangle(root.lecWs[hoverW])
                const b = meas.positionToRectangle(root.lecWe[hoverW])
                const ln = Math.round(a.y / root.natH)
                return [a.x, ln, Math.round(b.y / root.natH) === ln ? b.x - a.x : meas.width - a.x]
            }
            property int lastLine: -1
            onWrChanged: {
                const px = wr[0] - 3, pw = wr[2] + 6
                if (wr[1] !== lastLine || !hl.visible) {
                    // otra línea (o primera vez): la píldora aparece en su sitio, sin barrer
                    glide.stop()
                    hl.x = px; hl.width = pw; hl.y = wr[1] * root.lineH
                    lastLine = wr[1]
                } else {
                    gx.to = px; gw.to = pw
                    glide.restart()
                }
            }
            ParallelAnimation {
                id: glide
                NumberAnimation { id: gx; target: hl; property: "x"; duration: 150; easing.type: Easing.OutCubic }
                NumberAnimation { id: gw; target: hl; property: "width"; duration: 150; easing.type: Easing.OutCubic }
            }

            // la línea actual queda en la 2ª fila: se ve la anterior, la actual y la que viene
            Item {
                id: flow
                width: root.textW
                height: Math.max(meas.contentHeight, root.lineH)
                y: -Math.max(0, karaoke.curLine - 1) * root.lineH
                Behavior on y { NumberAnimation { duration: 380; easing.type: Easing.OutCubic } }

                component Cuerpo: Text {
                    width: root.textW
                    text: root.lecFlat
                    wrapMode: Text.WordWrap
                    lineHeightMode: Text.FixedHeight
                    lineHeight: root.lineH
                    font.family: root.fuente; font.pixelSize: root.kfont
                }
                // resalte sutil de la palabra bajo el puntero (detrás de todo el texto)
                Rectangle {
                    x: karaoke.hr[0] - 3; y: karaoke.hr[1] * root.lineH
                    width: karaoke.hr[2] + 6; height: root.lineH
                    radius: 6
                    color: "#1fffffff"
                    opacity: karaoke.hoverW >= 0 ? 1 : 0
                    Behavior on opacity { NumberAnimation { duration: 90 } }
                }
                Cuerpo { color: "#eceef1" }

                // lo ya leído, tenue: las líneas de arriba enteras...
                Item {
                    width: root.textW; height: hl.y
                    clip: true
                    Cuerpo { color: "#6d6e73" }
                }
                // ...y la línea actual hasta donde empieza la palabra
                Item {
                    x: 0; y: hl.y
                    width: Math.max(0, hl.x + 3); height: root.lineH
                    clip: true
                    Cuerpo { y: -parent.y; color: "#6d6e73" }
                }

                // palabra actual: píldora que se desliza, con la palabra en verde adentro
                Rectangle {
                    id: hl
                    height: root.lineH
                    radius: 6
                    color: "#1d3a2a"
                    clip: true
                    visible: karaoke.cw >= 0
                    Cuerpo { x: -hl.x; y: -hl.y; color: root.verde1 }
                    Rectangle {
                        anchors.left: parent.left; anchors.right: parent.right
                        anchors.bottom: parent.bottom; anchors.bottomMargin: 2
                        anchors.leftMargin: 3; anchors.rightMargin: 3
                        height: 2; radius: 1
                        color: root.verde0
                    }
                }
            }

            MouseArea {
                id: kma
                anchors.fill: parent
                hoverEnabled: true
                acceptedButtons: Qt.LeftButton
                cursorShape: karaoke.hoverW >= 0 ? Qt.PointingHandCursor : Qt.ArrowCursor
                onClicked: e => {
                    const w = karaoke.wordAtPoint(e.x, e.y - flow.y)
                    if (w >= 0) root.seekWord(w)
                }
            }
        }

        // estado bajo el texto: cuántas palabras, o «Esperando el próximo pedazo…»
        Text {
            id: statusLine
            x: 16; y: 12 + 3 * root.lineH + 4
            width: root.textW
            visible: root.hasText
            elide: Text.ElideRight
            font.family: root.fuente; font.pixelSize: 12
            color: root.stalled ? root.txt : root.txtMut
            text: root.stalled ? "Esperando el próximo pedazo…"
                               : "Leyendo · " + root.lecWords + " palabras" + (root.complete ? "" : " hasta ahora")
            SequentialAnimation on opacity {
                running: root.stalled && root.hasText
                loops: Animation.Infinite
                NumberAnimation { to: 0.45; duration: 700; easing.type: Easing.InOutSine }
                NumberAnimation { to: 1.0; duration: 700; easing.type: Easing.InOutSine }
                onRunningChanged: if (!running) statusLine.opacity = 1
            }
        }

        // controles: play/pausa · onda · tiempo · cerrar
        Item {
            id: line
            anchors.left: parent.left; anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.leftMargin: 6; anchors.rightMargin: 6; anchors.bottomMargin: 6
            height: root.btn
            visible: root.playUi

            RoundBtn {
                id: pbtn
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                tiled: true
                live: root.playing
                glyph: root.paused ? "play" : "pause"
                onClicked: bridge.togglePause()
            }
            RoundBtn {
                id: closeBtn
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                glyph: "x"
                onClicked: bridge.stop()
            }

            // tiempo: «0:12 / 0:48» (con «+» mientras el total sigue creciendo)
            Text {
                id: timeText
                anchors.right: closeBtn.left; anchors.rightMargin: 8
                anchors.verticalCenter: parent.verticalCenter
                width: 82
                horizontalAlignment: Text.AlignRight
                textFormat: Text.StyledText
                font.family: root.fuenteMed; font.pixelSize: 12
                color: root.txtMut
                text: (root.ready || root.exitHold)
                      ? '<font color="#f2f4f7">' + root.fmt(root.seeking ? root.seekTarget : root.globalPos) + '</font> <font color="#5d5f66">/</font> ' +
                        root.fmt(root.totalDur) + (root.complete ? "" : "+")
                      : "—:—"
            }

            // ---- la onda: progreso + arrastre para buscar ----
            Item {
                id: wave
                anchors.left: pbtn.right; anchors.leftMargin: 8
                anchors.right: timeText.left; anchors.rightMargin: 8
                anchors.verticalCenter: parent.verticalCenter
                height: root.waveH
                // el hueco entre trozos se ve como una leve atenuación; pausado baja a .4
                opacity: (!root.ready && !root.exitHold) ? 0.4 : (root.paused ? 0.4 : (root.stalled ? 0.72 : 1.0))
                Behavior on opacity { NumberAnimation { duration: 120 } }

                readonly property real barW: (width - (root.wbars - 1) * root.barGap) / root.wbars

                Row {
                    anchors.fill: parent
                    spacing: root.barGap
                    Repeater {
                        model: root.wbars
                        Rectangle {
                            width: wave.barW
                            radius: 1.5
                            color: root.barColor(index)
                            anchors.verticalCenter: parent.verticalCenter
                            height: root.barH(index)
                            Behavior on height { NumberAnimation { duration: 130; easing.type: Easing.OutCubic } }
                            Behavior on color { ColorAnimation { duration: 130 } }
                        }
                    }
                }

                MouseArea {
                    id: seekMA
                    anchors.fill: parent; anchors.topMargin: -8; anchors.bottomMargin: -8
                    hoverEnabled: true
                    enabled: root.ready
                    cursorShape: Qt.PointingHandCursor
                    function seekTo(mx) {
                        if (root.totalDur <= 0) return
                        const f = root.clamp(mx / wave.width, 0, 1)
                        root.seekGlobal(f * root.totalDur)        // feedback inmediato adentro
                    }
                    onPressed: e => { root.seeking = true; seekTo(e.x) }
                    onPositionChanged: e => { if (pressed) seekTo(e.x) }
                    onReleased: e => {
                        seekTo(e.x)
                        root.visPos = root.globalPos
                        bridge.seek(root.globalPos)
                        root.seeking = false
                    }
                }
            }
        }

        // etiqueta con el destino mientras arrastrás (del lado de adentro de la pantalla)
        Rectangle {
            visible: root.seeking && root.playing
            y: root.atTop ? pill.height + 8 : -height - 8
            x: root.clamp(wave.mapToItem(pill, seekMA.mouseX, 0).x - width / 2, 0, pill.width - width)
            width: tipTxt.implicitWidth + 16
            height: 24; radius: 12
            color: root.fondo; border.color: "#4dd5eadc"; border.width: 1
            Text {
                id: tipTxt
                anchors.centerIn: parent
                text: root.fmt(root.seekTarget)
                color: root.txt
                font.family: root.fuenteMed; font.pixelSize: 12
            }
        }
    }
}
