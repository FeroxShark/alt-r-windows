// Ventana de Configuración de AltR. Mismo lenguaje que el overlay (Overlay.qml): vidrio
// semitransparente #ec0e0c12, verde del TTS #3ddc84 -> #7dffb0, Inter; y las proporciones del
// estándar de Ferox (grilla de 4, radios 10/14/28, cápsulas de 32-36, interruptor 40x24,
// riel de 4 con perilla de 16, foco de teclado de 2 px).
//
// Sólo `import QtQuick` (sin Controls ni Layouts: el .exe los recorta). El modelo es el objeto
// `ctl` (altr/settings.py, SettingsController): `ctl.values` trae el formulario, `ctl.set(clave, v)`
// lo edita, `ctl.save()` lo guarda en el config.toml y recarga AltR.

import QtQuick

Item {
    id: root

    property string seccion: "atajos"
    property bool ready: false

    // ---- geometría ----
    readonly property int m: 24                    // margen para la sombra
    readonly property int winW: 832
    readonly property int winH: 608
    readonly property int sideW: 196
    readonly property int pad: 28
    readonly property int footH: 68
    width: winW + 2 * m
    height: winH + 2 * m

    // ---- paleta (la del overlay) ----
    readonly property color verde0: "#3ddc84"
    readonly property color verde1: "#7dffb0"
    readonly property color critico: "#f26d6d"
    readonly property color aviso: "#f2c35a"
    readonly property color okc: "#7ad69b"
    readonly property color txt: "#f2f4f7"
    readonly property color txtMut: "#a3a6ad"
    readonly property color txtDis: "#5d5f66"
    readonly property color tile: "#18ffffff"
    readonly property color tileHover: "#29ffffff"
    readonly property color cardC: "#0cffffff"
    readonly property color divC: "#12ffffff"
    readonly property color sobreVerde: "#06210f"

    FontLoader { id: fReg; source: Qt.resolvedUrl("../fonts/Inter-Regular.ttf") }
    FontLoader { id: fMed; source: Qt.resolvedUrl("../fonts/Inter-Medium.ttf") }
    readonly property string fuente: fReg.status === FontLoader.Ready ? fReg.name : "Segoe UI"
    readonly property string fuenteMed: fMed.status === FontLoader.Ready ? fMed.name : "Segoe UI Semibold"

    readonly property var secciones: [
        { id: "atajos", t: "Atajos", d: "Con qué teclas se lee y se corta, y cómo se captura el texto." },
        { id: "voz", t: "Voz", d: "El motor, la voz y cómo suena." },
        { id: "api", t: "Modelo / API", d: "El servicio compatible con OpenAI y su clave." },
        { id: "overlay", t: "Overlay", d: "La cápsula que aparece mientras se lee." },
        { id: "general", t: "General", d: "Inicio, avisos, versión y archivos." }
    ]
    readonly property var seccionActual: {
        for (let i = 0; i < secciones.length; i++) if (secciones[i].id === seccion) return secciones[i]
        return secciones[0]
    }
    function val(k) { return ctl.values[k] }
    function provider() { return String(ctl.values["tts.provider"]) }

    // sección a la que pertenece el error del formulario (para el punto rojo del menú)
    readonly property string errSeccion: {
        const k = String(ctl.errorKey)
        if (k === "") return ""
        if (k.indexOf("general.hotkey") === 0 || k.indexOf("general.stop_hotkey") === 0) return "atajos"
        if (k.indexOf("tts.") === 0 || k.indexOf("edge.") === 0 || k.indexOf("command.") === 0) return "voz"
        if (k.indexOf("openai.") === 0) return "api"
        if (k.indexOf("overlay.") === 0) return "overlay"
        return ""
    }

    property bool closeArmed: false
    property bool capturingAny: false      // un campo de atajo está capturando: los atajos de la ventana se apagan
    Timer { id: closeTimer; interval: 4000; onTriggered: root.closeArmed = false }
    function tryClose() {
        if (ctl.dirty && !closeArmed) { closeArmed = true; closeTimer.restart(); return }
        closeArmed = false
        if (ctl.dirty) ctl.revert()
        ctl.closeWindow()
    }
    Connections { target: ctl; function onDirtyChanged() { if (!ctl.dirty) root.closeArmed = false } }

    Component.onCompleted: ready = true
    Shortcut { sequence: "Ctrl+S"; enabled: !root.capturingAny; onActivated: if (ctl.dirty && ctl.error === "") ctl.save() }
    Shortcut { sequence: "Esc"; enabled: !root.capturingAny; onActivated: root.tryClose() }

    // =============================================================== piezas
    component Btn: Rectangle {
        id: b
        property string label: ""
        property bool primary: false
        property bool danger: false
        signal clicked()
        property bool hov: ma.containsMouse && enabled
        implicitWidth: lbl.implicitWidth + 32
        width: implicitWidth
        height: 36; radius: 18
        opacity: enabled ? 1 : 0.4
        color: primary ? (hov ? root.verde1 : root.verde0) : (hov ? root.tileHover : root.tile)
        scale: ma.pressed ? 0.97 : 1
        activeFocusOnTab: true
        Behavior on color { ColorAnimation { duration: 120 } }
        Behavior on scale { NumberAnimation { duration: 90; easing.type: Easing.OutCubic } }
        Behavior on opacity { NumberAnimation { duration: 140 } }
        Keys.onSpacePressed: if (enabled) clicked()
        Keys.onReturnPressed: if (enabled) clicked()
        Rectangle {
            anchors.fill: parent; anchors.margins: -3; radius: height / 2
            color: "transparent"; border.width: 2; border.color: root.verde1
            visible: b.activeFocus
        }
        Text {
            id: lbl
            anchors.centerIn: parent
            text: b.label
            color: b.primary ? root.sobreVerde : (b.danger ? root.critico : root.txt)
            font.family: root.fuenteMed; font.pixelSize: 13
        }
        MouseArea {
            id: ma; anchors.fill: parent; hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: if (b.enabled) b.clicked()
        }
    }

    component Toggle: Item {
        id: tg
        property string key: ""
        readonly property bool on: root.val(key) === true
        width: 40; height: 24
        activeFocusOnTab: true
        opacity: enabled ? 1 : 0.4
        Keys.onSpacePressed: flip()
        Keys.onReturnPressed: flip()
        function flip() { if (enabled) ctl.set(key, !on) }
        Rectangle {
            anchors.fill: parent; radius: 12
            color: tg.on ? root.verde0 : "#2effffff"
            Behavior on color { ColorAnimation { duration: 140 } }
        }
        Rectangle {
            width: 16; height: 16; radius: 8
            anchors.verticalCenter: parent.verticalCenter
            x: tg.on ? parent.width - width - 4 : 4
            color: tg.on ? root.sobreVerde : root.txt
            Behavior on x { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
            Behavior on color { ColorAnimation { duration: 140 } }
        }
        Rectangle {
            anchors.fill: parent; anchors.margins: -3; radius: height / 2
            color: "transparent"; border.width: 2; border.color: root.verde1
            visible: tg.activeFocus
        }
    }

    // fila: título + detalle a la izquierda, el control a la derecha; toda la fila de un interruptor
    // es zona de clic (`toggleKey`)
    component SRow: Item {
        id: sr
        default property alias control: slot.data
        property string label: ""
        property string hint: ""
        property color hintColor: root.txtMut
        property string toggleKey: ""
        property bool stacked: false      // el control va debajo del texto, a todo el ancho
        width: parent ? parent.width : 0
        implicitHeight: stacked ? textCol.height + slot.height + 28 : Math.max(52, textCol.height + 22)
        height: implicitHeight
        Rectangle {
            visible: sr.y > 1
            anchors.top: parent.top; anchors.left: parent.left; anchors.right: parent.right
            anchors.leftMargin: 16; anchors.rightMargin: 16
            height: 1; color: root.divC
        }
        Rectangle {
            anchors.fill: parent; radius: 14
            color: rowMa.containsMouse ? "#0affffff" : "transparent"
            Behavior on color { ColorAnimation { duration: 120 } }
        }
        MouseArea {
            id: rowMa
            anchors.fill: parent
            hoverEnabled: sr.toggleKey !== ""
            enabled: sr.toggleKey !== ""
            cursorShape: sr.toggleKey !== "" ? Qt.PointingHandCursor : Qt.ArrowCursor
            onClicked: ctl.set(sr.toggleKey, root.val(sr.toggleKey) !== true)
        }
        Column {
            id: textCol
            x: 16; y: sr.stacked ? 14 : (sr.height - height) / 2
            width: sr.stacked ? sr.width - 32 : sr.width - 32 - slot.width - 16
            spacing: 2
            Text {
                width: parent.width
                text: sr.label; color: root.txt; elide: Text.ElideRight
                font.family: root.fuente; font.pixelSize: 13
            }
            Text {
                visible: sr.hint !== ""
                width: parent.width
                text: sr.hint; color: sr.hintColor; wrapMode: Text.WordWrap
                font.family: root.fuente; font.pixelSize: 12
            }
        }
        Item {
            id: slot
            width: childrenRect.width; height: childrenRect.height
            x: sr.stacked ? 16 : sr.width - 16 - width
            y: sr.stacked ? textCol.y + textCol.height + 10 : (sr.height - height) / 2
        }
    }

    component Card: Column {
        id: cd
        property string title: ""
        default property alias rows: body.data
        width: parent ? parent.width : 0
        spacing: 8
        Text {
            visible: cd.title !== ""
            leftPadding: 4
            text: cd.title; color: root.txtMut
            font.family: root.fuenteMed; font.pixelSize: 12
        }
        Rectangle {
            width: parent.width; height: body.height
            radius: 14; color: root.cardC
            Column { id: body; width: parent.width }
        }
    }

    component Note: Text {
        width: parent ? parent.width : 0
        wrapMode: Text.WordWrap
        color: root.txtMut
        font.family: root.fuente; font.pixelSize: 12
        leftPadding: 4; rightPadding: 4
    }

    component Field: Rectangle {
        id: fl
        property string key: ""
        property string placeholder: ""
        property bool password: false
        property alias text: ti.text
        readonly property bool bad: key !== "" && ctl.errorKey === key
        signal submitted(string text)
        width: 260; height: 36; radius: 10
        color: root.tile
        border.width: ti.activeFocus || bad ? 2 : 0
        border.color: bad ? root.critico : root.verde1
        TextInput {
            id: ti
            anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 12
            verticalAlignment: TextInput.AlignVCenter
            clip: true; selectByMouse: true
            color: root.txt; selectionColor: root.verde0; selectedTextColor: root.sobreVerde
            font.family: root.fuente; font.pixelSize: 13
            echoMode: fl.password ? TextInput.Password : TextInput.Normal
            text: fl.key !== "" ? String(root.val(fl.key)) : ""
            onTextEdited: if (fl.key !== "") ctl.set(fl.key, text)
            onAccepted: fl.submitted(text)
        }
        Text {
            anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 12
            verticalAlignment: Text.AlignVCenter
            visible: ti.text === "" && !ti.preeditText
            text: fl.placeholder; color: root.txtDis; elide: Text.ElideRight
            font.family: root.fuente; font.pixelSize: 13
        }
        function clear() { ti.text = "" }
    }

    component Slide: Item {
        id: sl
        property string key: ""
        property real from: 0
        property real to: 1
        property real step: 0.1
        property int decimals: 1
        property string suffix: ""
        property real scaleFactor: 1       // 0.925 -> "93 %": se muestra value * scaleFactor
        readonly property real value: Number(root.val(key))
        readonly property real frac: Math.max(0, Math.min(1, (value - from) / (to - from)))
        width: 252; height: 32
        activeFocusOnTab: true
        Keys.onLeftPressed: nudge(-1)
        Keys.onRightPressed: nudge(1)
        function nudge(d) { ctl.set(key, Math.max(from, Math.min(to, value + d * step))) }
        function setFromX(x) {
            const f = Math.max(0, Math.min(1, (x - 8) / (track.width - 16)))
            const v = from + f * (to - from)
            ctl.set(key, Math.max(from, Math.min(to, Math.round(v / step) * step)))
        }
        Item {
            id: track
            anchors.left: parent.left; anchors.right: readout.left; anchors.rightMargin: 12
            height: parent.height
            Rectangle {
                x: 8; width: parent.width - 16; height: 4; radius: 2
                anchors.verticalCenter: parent.verticalCenter
                color: "#29ffffff"
                Rectangle { width: parent.width * sl.frac; height: parent.height; radius: 2; color: root.verde0 }
            }
            Rectangle {
                id: halo
                width: 32; height: 32; radius: 16
                x: 8 + (track.width - 16) * sl.frac - 16
                anchors.verticalCenter: parent.verticalCenter
                color: root.verde1
                opacity: sma.pressed ? 0.22 : (sma.containsMouse || sl.activeFocus ? 0.12 : 0)
                Behavior on opacity { NumberAnimation { duration: 120 } }
            }
            Rectangle {
                width: 16; height: 16; radius: 8
                x: halo.x + 8
                anchors.verticalCenter: parent.verticalCenter
                color: root.txt
                border.width: sl.activeFocus ? 2 : 0; border.color: root.verde1
            }
            MouseArea {
                id: sma; anchors.fill: parent; hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onPressed: (e) => sl.setFromX(e.x)
                onPositionChanged: (e) => { if (pressed) sl.setFromX(e.x) }
            }
        }
        Text {
            id: readout
            anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
            width: 56; horizontalAlignment: Text.AlignRight
            text: (sl.value * sl.scaleFactor).toFixed(sl.decimals) + sl.suffix
            color: root.txt; font.family: root.fuenteMed; font.pixelSize: 13
        }
    }

    // opciones en cápsulas (una sola elegida)
    component Chips: Flow {
        id: ch
        property var model: []            // [{v, t}]
        property string current: ""
        signal picked(string v)
        spacing: 8
        Repeater {
            model: ch.model
            delegate: Rectangle {
                required property var modelData
                readonly property bool sel: modelData.v === ch.current
                height: 32; radius: 16
                width: cl.implicitWidth + 22
                color: sel ? root.verde0 : (cma.containsMouse ? root.tileHover : root.tile)
                scale: cma.pressed ? 0.97 : 1
                activeFocusOnTab: true
                Keys.onSpacePressed: ch.picked(modelData.v)
                Keys.onReturnPressed: ch.picked(modelData.v)
                Behavior on color { ColorAnimation { duration: 140 } }
                Behavior on scale { NumberAnimation { duration: 90 } }
                Rectangle {
                    anchors.fill: parent; anchors.margins: -3; radius: height / 2
                    color: "transparent"; border.width: 2; border.color: root.verde1
                    visible: parent.activeFocus
                }
                Text {
                    id: cl
                    anchors.centerIn: parent
                    text: modelData.t
                    color: parent.sel ? root.sobreVerde : root.txt
                    font.family: root.fuenteMed; font.pixelSize: 12
                    Behavior on color { ColorAnimation { duration: 140 } }
                }
                MouseArea {
                    id: cma; anchors.fill: parent; hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: ch.picked(modelData.v)
                }
            }
        }
    }

    // un atajo: teclas dibujadas + "Cambiar" (captura) [+ "Quitar"]
    component HotkeyField: Item {
        id: hf
        property string key: ""
        property string which: "read"          // read | stop
        property bool allowClear: false
        property bool capturing: false
        property string live: ""
        property string capErr: ""
        readonly property string value: String(root.val(key) || "")
        readonly property string k1: String(root.val("general.hotkey") || "")
        readonly property string k2: String(root.val("general.stop_hotkey") || "")
        readonly property var chk: {
            const _a = k1, _b = k2
            return ctl.checkHotkey(which, which === "read" ? _a : _b)
        }
        readonly property string msg: capErr !== "" ? capErr : (capturing || chk.state === "own" ? "" : (chk.msg || ""))
        readonly property color msgColor: capErr !== "" ? root.critico
            : (chk.state === "free" ? root.okc : (chk.state === "taken" || chk.state === "dup" ? root.critico : root.txtMut))
        width: row.width; height: 36

        function keyLabel(p) {
            const m = { ctrl: "Ctrl", alt: "Alt", shift: "Shift", win: "Win", space: "Espacio", enter: "Enter",
                        esc: "Esc", tab: "Tab", up: "↑", down: "↓", left: "←", right: "→" }
            return m[p] !== undefined ? m[p] : p.toUpperCase()
        }
        function startCapture() {
            capErr = ""; live = ""; capturing = true
            root.capturingAny = true
            ctl.setCapturing(true)
            cap.forceActiveFocus()
        }
        function stopCapture() {
            capturing = false; live = ""
            root.capturingAny = false
            ctl.setCapturing(false)
            root.forceActiveFocus()
        }
        Component.onDestruction: if (capturing) { root.capturingAny = false; ctl.setCapturing(false) }

        Row {
            id: row
            spacing: 8
            // las teclas del atajo actual
            Row {
                spacing: 4
                anchors.verticalCenter: parent.verticalCenter
                visible: !hf.capturing
                Repeater {
                    model: hf.value === "" ? [] : hf.value.split("+")
                    delegate: Rectangle {
                        required property string modelData
                        height: 28; width: Math.max(28, kt.implicitWidth + 16); radius: 8
                        color: root.tile
                        border.width: 1; border.color: "#1fffffff"
                        Text {
                            id: kt; anchors.centerIn: parent
                            text: hf.keyLabel(modelData); color: root.txt
                            font.family: root.fuenteMed; font.pixelSize: 12
                        }
                    }
                }
                Text {
                    visible: hf.value === ""
                    anchors.verticalCenter: parent.verticalCenter
                    text: "Ninguno"; color: root.txtMut
                    font.family: root.fuente; font.pixelSize: 13
                }
            }
            // captura: "apretá el atajo"
            Rectangle {
                id: cap
                visible: hf.capturing
                width: 200; height: 36; radius: 18
                color: "#1a3ddc84"
                border.width: 2; border.color: root.verde1
                focus: hf.capturing
                activeFocusOnTab: false
                anchors.verticalCenter: parent.verticalCenter
                SequentialAnimation on border.color {
                    running: hf.capturing; loops: Animation.Infinite
                    ColorAnimation { to: root.verde0; duration: 700 }
                    ColorAnimation { to: root.verde1; duration: 700 }
                }
                Text {
                    anchors.centerIn: parent
                    text: hf.live !== "" ? hf.live.split("+").map(hf.keyLabel).join(" + ") + " + …" : "Apretá el atajo…"
                    color: root.txt; font.family: root.fuenteMed; font.pixelSize: 13
                }
                onActiveFocusChanged: if (!activeFocus && hf.capturing) hf.stopCapture()
                Keys.onPressed: (e) => {
                    e.accepted = true
                    if (e.key === Qt.Key_Escape) { hf.stopCapture(); return }
                    const r = ctl.captureKey(e.key, e.modifiers)
                    hf.live = r.text
                    hf.capErr = r.error
                    if (r.done) {
                        ctl.set(hf.key, r.text)
                        hf.stopCapture()
                    }
                }
            }
            Btn {
                label: hf.capturing ? "Cancelar" : "Cambiar"
                anchors.verticalCenter: parent.verticalCenter
                onClicked: hf.capturing ? hf.stopCapture() : hf.startCapture()
            }
            Btn {
                visible: hf.allowClear && hf.value !== "" && !hf.capturing
                label: "Quitar"
                anchors.verticalCenter: parent.verticalCenter
                onClicked: { hf.capErr = ""; ctl.set(hf.key, "") }
            }
        }
    }

    // ---- vista previa en vivo del overlay (la misma cápsula, más chica) ----
    component Preview: Item {
        id: pv
        readonly property string pos: String(root.val("overlay.position"))
        readonly property bool enabledOv: root.val("overlay.enabled") === true
        readonly property real op: Number(root.val("overlay.opacity"))
        readonly property real fs: Number(root.val("overlay.font_size"))
        readonly property real sc: 0.62
        readonly property real lineH: Math.ceil(fs * sc * 1.3 * 1.3)
        readonly property real capW: 704 * sc
        readonly property real capH: 28 + 3 * lineH + 10 + 28
        readonly property real gap: 16 * sc
        width: parent ? parent.width : 0
        height: 220

        Rectangle {
            id: scr
            anchors.fill: parent
            radius: 14; clip: true
            gradient: Gradient {
                orientation: Gradient.Vertical
                GradientStop { position: 0; color: "#27304a" }
                GradientStop { position: 1; color: "#161b2b" }
            }
            // un "programa" de fondo, para que se note la transparencia del vidrio
            Rectangle {
                x: parent.width * 0.12; y: 20; width: parent.width * 0.52; height: parent.height - 60
                radius: 8; color: "#e9edf5"
                Column {
                    x: 16; y: 16; spacing: 10; width: parent.width - 32
                    Repeater {
                        model: [0.9, 0.72, 0.84, 0.5, 0.8, 0.66, 0.78, 0.4]
                        delegate: Rectangle { required property real modelData
                            width: parent.width * modelData; height: 6; radius: 3; color: "#aeb6c6" }
                    }
                }
            }
            Rectangle {
                x: parent.width * 0.5; y: 56; width: parent.width * 0.38; height: parent.height - 86
                radius: 8; color: "#243253"
            }

            Rectangle {
                id: cap
                width: pv.capW; height: pv.capH
                radius: 14
                readonly property bool arriba: pv.pos.indexOf("top") === 0
                readonly property bool izq: pv.pos.indexOf("left") > 0
                readonly property bool der: pv.pos.indexOf("right") > 0
                x: izq ? pv.gap : (der ? scr.width - width - pv.gap : (scr.width - width) / 2)
                y: arriba ? pv.gap : scr.height - height - pv.gap
                color: Qt.rgba(14 / 255, 12 / 255, 18 / 255, pv.op)
                border.width: 1; border.color: "#4dd5eadc"
                opacity: pv.enabledOv ? 1 : 0.25
                Behavior on x { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
                Behavior on y { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
                Behavior on opacity { NumberAnimation { duration: 160 } }
                Behavior on height { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
                Rectangle {
                    anchors.fill: parent; anchors.margins: 1; radius: parent.radius - 1
                    gradient: Gradient {
                        GradientStop { position: 0.0; color: "#12f4f5f7" }
                        GradientStop { position: 0.55; color: "#00f4f5f7" }
                    }
                }
                Text {
                    x: 12; y: 10; width: parent.width - 24; height: 3 * pv.lineH
                    clip: true; wrapMode: Text.WordWrap
                    lineHeight: 1.3 * 1.3 / 1.3; lineHeightMode: Text.ProportionalHeight
                    textFormat: Text.StyledText
                    font.family: root.fuente; font.pixelSize: pv.fs * pv.sc
                    color: root.txt
                    text: "<font color='#5d5f66'>Así se ve AltR mientras lee. </font>"
                        + "<font color='#7dffb0'><b>La palabra</b></font> que suena se marca en verde y las "
                        + "que ya pasaron se apagan. Podés pausar con el botón de la izquierda o saltar con un clic en la onda."
                }
                Row {
                    x: 8; anchors.bottom: parent.bottom; anchors.bottomMargin: 6
                    spacing: 8; height: 22
                    Rectangle { width: 22; height: 22; radius: 11; color: "#18ffffff"
                        Row { anchors.centerIn: parent; spacing: 3
                            Rectangle { width: 2.5; height: 9; radius: 1; color: root.txt }
                            Rectangle { width: 2.5; height: 9; radius: 1; color: root.txt } } }
                    Row {
                        spacing: 1.5; anchors.verticalCenter: parent.verticalCenter
                        Repeater {
                            model: 34
                            delegate: Rectangle {
                                required property int index
                                width: 2.4; radius: 1
                                height: 3 + 11 * Math.abs(Math.sin(index * 0.7) * Math.cos(index * 0.23))
                                anchors.verticalCenter: parent.verticalCenter
                                color: index < 13 ? root.verde0 : "#38ffffff"
                            }
                        }
                    }
                    Text { anchors.verticalCenter: parent.verticalCenter; text: "0:08 / 0:14"
                        color: root.txtMut; font.family: root.fuente; font.pixelSize: 10 }
                }
            }
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: (e) => {
                    const c = e.x < width / 3 ? "left" : (e.x > 2 * width / 3 ? "right" : "center")
                    ctl.set("overlay.position", (e.y < height / 2 ? "top-" : "bottom-") + c)
                }
            }
        }
        Rectangle { anchors.fill: scr; radius: 14; color: "transparent"; border.width: 1; border.color: "#1fffffff" }
    }

    readonly property var posNombres: ({
        "bottom-center": "Abajo, al centro", "bottom-left": "Abajo, a la izquierda",
        "bottom-right": "Abajo, a la derecha", "top-center": "Arriba, al centro",
        "top-left": "Arriba, a la izquierda", "top-right": "Arriba, a la derecha" })

    readonly property var regiones: ({
        AR: "Argentina", ES: "España", MX: "México", CO: "Colombia", US: "Estados Unidos", GB: "Reino Unido",
        BR: "Brasil", PT: "Portugal", FR: "Francia", DE: "Alemania", IT: "Italia", CL: "Chile", PE: "Perú",
        UY: "Uruguay", VE: "Venezuela", BO: "Bolivia", EC: "Ecuador", PY: "Paraguay", CU: "Cuba",
        DO: "R. Dominicana", GT: "Guatemala", HN: "Honduras", NI: "Nicaragua", PA: "Panamá", PR: "Puerto Rico",
        SV: "El Salvador", CR: "Costa Rica", GQ: "Guinea Ecuatorial", CA: "Canadá", AU: "Australia",
        IN: "India", IE: "Irlanda", NZ: "Nueva Zelanda", ZA: "Sudáfrica", CH: "Suiza", AT: "Austria" })

    // =============================================================== ventana
    // sombra suave (capas sin blur: los efectos de Qt no van en el .exe)
    Repeater {
        model: 7
        delegate: Rectangle {
            required property int index
            anchors.fill: glass
            anchors.margins: -(index + 1) * 3
            anchors.topMargin: -(index + 1) * 3 + 8
            anchors.bottomMargin: -(index + 1) * 3 - 8
            radius: glass.radius + (index + 1) * 3
            color: "#000000"; opacity: 0.045
        }
    }

    Rectangle {
        id: glass
        x: root.m; y: root.m; width: root.winW; height: root.winH
        radius: 28
        color: "#ec0e0c12"
        border.width: 1; border.color: "#4dd5eadc"
        Rectangle {
            anchors.fill: parent; anchors.margins: 1; radius: parent.radius - 1
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#12f4f5f7" }
                GradientStop { position: 0.4; color: "#00f4f5f7" }
            }
        }

        // arrastrar la ventana desde la franja de arriba
        MouseArea {
            x: 0; y: 0; width: parent.width - 96; height: 56
            onPressed: ctl.startMove()
        }

        // ------------------------------------------------ barra lateral
        Item {
            id: side
            x: 0; y: 0; width: root.sideW; height: parent.height
            Rectangle { anchors.right: parent.right; y: 20; width: 1; height: parent.height - 40; color: root.divC }
            MouseArea { x: 0; y: 0; width: parent.width; height: 56; onPressed: ctl.startMove() }
            Column {
                x: 24; y: 24; spacing: 2
                Text { text: "AltR"; color: root.txt; font.family: root.fuenteMed; font.pixelSize: 16 }
                Text { text: "Configuración"; color: root.txtMut; font.family: root.fuente; font.pixelSize: 12 }
            }
            Column {
                x: 12; y: 92; width: parent.width - 24; spacing: 4
                Repeater {
                    model: root.secciones
                    delegate: Rectangle {
                        id: si
                        required property var modelData
                        readonly property bool sel: root.seccion === modelData.id
                        width: parent.width; height: 40; radius: 10
                        color: sel ? "#383ddc84" : (sma2.containsMouse ? "#12ffffff" : "transparent")
                        activeFocusOnTab: true
                        Keys.onSpacePressed: root.seccion = modelData.id
                        Keys.onReturnPressed: root.seccion = modelData.id
                        Behavior on color { ColorAnimation { duration: 140 } }
                        Rectangle {
                            anchors.fill: parent; anchors.margins: -2; radius: 12
                            color: "transparent"; border.width: 2; border.color: root.verde1
                            visible: si.activeFocus
                        }
                        Text {
                            x: 14; anchors.verticalCenter: parent.verticalCenter
                            text: modelData.t
                            color: si.sel ? root.verde1 : root.txt
                            font.family: root.fuenteMed; font.pixelSize: 13
                            Behavior on color { ColorAnimation { duration: 140 } }
                        }
                        Rectangle {
                            visible: root.errSeccion === modelData.id
                            anchors.right: parent.right; anchors.rightMargin: 14
                            anchors.verticalCenter: parent.verticalCenter
                            width: 8; height: 8; radius: 4; color: root.critico
                        }
                        MouseArea {
                            id: sma2; anchors.fill: parent; hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.seccion = modelData.id
                        }
                    }
                }
            }
        }

        // ------------------------------------------------ botones de la ventana
        Row {
            anchors.right: parent.right; anchors.rightMargin: 16; y: 14
            spacing: 4
            Rectangle {
                width: 32; height: 32; radius: 16
                color: minMa.containsMouse ? root.tileHover : "transparent"
                Behavior on color { ColorAnimation { duration: 100 } }
                Rectangle { anchors.centerIn: parent; width: 12; height: 2; radius: 1; color: root.txtMut }
                MouseArea { id: minMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                    onClicked: ctl.minimize() }
            }
            Rectangle {
                width: 32; height: 32; radius: 16
                color: closeMa.containsMouse ? (root.closeArmed ? "#40f26d6d" : root.tileHover)
                                             : (root.closeArmed ? "#30f26d6d" : "transparent")
                Behavior on color { ColorAnimation { duration: 100 } }
                Rectangle { anchors.centerIn: parent; width: 14; height: 2; radius: 1; rotation: 45
                    color: root.closeArmed ? root.critico : root.txtMut }
                Rectangle { anchors.centerIn: parent; width: 14; height: 2; radius: 1; rotation: -45
                    color: root.closeArmed ? root.critico : root.txtMut }
                MouseArea { id: closeMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                    onClicked: root.tryClose() }
            }
        }

        // ------------------------------------------------ contenido
        Item {
            id: main
            x: root.sideW; y: 0; width: parent.width - root.sideW; height: parent.height

            Column {
                x: root.pad; y: 22; width: parent.width - 2 * root.pad - 80; spacing: 4
                Text { text: root.seccionActual.t; color: root.txt
                    font.family: root.fuenteMed; font.pixelSize: 20 }
                Text { width: parent.width; text: root.seccionActual.d; color: root.txtMut; elide: Text.ElideRight
                    font.family: root.fuente; font.pixelSize: 13 }
            }

            Flickable {
                id: flick
                x: 0; y: 84; width: parent.width; height: parent.height - 84 - root.footH
                contentWidth: width; contentHeight: content.height + 24
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                flickableDirection: Flickable.VerticalFlick

                Column {
                    id: content
                    x: root.pad; y: 4; width: flick.width - 2 * root.pad; spacing: 20
                    opacity: 1
                    NumberAnimation on opacity { id: secFade; from: 0; to: 1; duration: 180
                        easing.type: Easing.OutCubic; running: false }

                    // ====================================================== ATAJOS
                    Column {
                        width: parent.width; spacing: 20
                        visible: root.seccion === "atajos"
                        Card {
                            title: "Atajos globales"
                            SRow {
                                label: "Leer la selección"
                                hint: hkRead.msg !== "" ? hkRead.msg : "Funciona en cualquier programa."
                                hintColor: hkRead.msg !== "" ? hkRead.msgColor : root.txtMut
                                HotkeyField { id: hkRead; key: "general.hotkey"; which: "read" }
                            }
                            SRow {
                                label: "Cortar la lectura"
                                hint: hkStop.msg !== "" ? hkStop.msg : "También se corta desde la X de la cápsula o el ícono de la bandeja."
                                hintColor: hkStop.msg !== "" ? hkStop.msgColor : root.txtMut
                                HotkeyField { id: hkStop; key: "general.stop_hotkey"; which: "stop"; allowClear: true }
                            }
                        }
                        Note {
                            text: "Apretá «Cambiar» y después las teclas (con Ctrl, Alt, Shift o Win); Esc cancela. "
                                + "Alt+R solo suele estar tomado por la NVIDIA App."
                        }
                        Card {
                            title: "Captura del texto"
                            SRow { label: "Leer el portapapeles si no hay nada seleccionado"
                                toggleKey: "general.clipboard_fallback"
                                Toggle { key: "general.clipboard_fallback" } }
                            SRow { label: "Devolver el portapapeles como estaba"
                                hint: "AltR copia la selección con Ctrl+C; después te lo deja como antes (sólo texto)."
                                toggleKey: "general.restore_clipboard"
                                Toggle { key: "general.restore_clipboard" } }
                        }
                    }

                    // ====================================================== VOZ
                    Column {
                        width: parent.width; spacing: 20
                        visible: root.seccion === "voz"
                        Card {
                            title: "Motor de voz"
                            SRow {
                                stacked: true
                                label: "Quién genera la voz"
                                hint: root.provider() === "edge" ? "Voces neuronales de Microsoft Edge: gratis, sin cuenta, necesita internet."
                                    : (root.provider() === "openai" ? "Una API compatible con OpenAI (se configura en «Modelo / API»)."
                                    : "Un programa local, como Piper (sus argumentos están en el config.toml).")
                                Chips {
                                    width: 520
                                    model: [{ v: "edge", t: "Microsoft Edge" }, { v: "openai", t: "API compatible con OpenAI" },
                                            { v: "command", t: "Programa local" }]
                                    current: root.provider()
                                    onPicked: (v) => ctl.set("tts.provider", v)
                                }
                            }
                        }
                        // --- voz de Edge: filtrable por idioma
                        Card {
                            id: edgeCard
                            visible: root.provider() === "edge"
                            title: "Voz"
                            property string lang: "es"
                            property string query: ""
                            readonly property var voicesAll: ctl.voices
                            readonly property var shown: {
                                const q = query.trim().toLowerCase()
                                const out = []
                                const all = voicesAll
                                for (let i = 0; i < all.length; i++) {
                                    const v = all[i]
                                    if (lang !== "" && String(v.locale).split("-")[0] !== lang) continue
                                    if (q !== "" && (String(v.name) + " " + String(v.locale)).toLowerCase().indexOf(q) < 0) continue
                                    out.push(v)
                                }
                                return out
                            }
                            Component.onCompleted: {
                                const cur = String(root.val("edge.voice")).split("-")[0].toLowerCase()
                                if (cur !== "") lang = cur
                            }
                            SRow {
                                stacked: true
                                label: "Idioma"
                                Chips {
                                    width: 520
                                    model: [{ v: "es", t: "Español" }, { v: "en", t: "Inglés" }, { v: "pt", t: "Portugués" },
                                            { v: "fr", t: "Francés" }, { v: "de", t: "Alemán" }, { v: "it", t: "Italiano" },
                                            { v: "", t: "Todos" }]
                                    current: edgeCard.lang
                                    onPicked: (v) => edgeCard.lang = v
                                }
                            }
                            SRow {
                                stacked: true
                                visible: ctl.voicesState === "ready"
                                label: "Voz elegida: " + String(root.val("edge.voice"))
                                Column {
                                    spacing: 8
                                    Field { id: voiceSearch; width: 540; placeholder: "Buscar por nombre o país…"
                                        onTextChanged: edgeCard.query = text }
                                    Rectangle {
                                        width: 540; height: 208; radius: 10; color: "#0affffff"; clip: true
                                        ListView {
                                            id: vlist
                                            anchors.fill: parent; anchors.margins: 4
                                            model: edgeCard.shown
                                            boundsBehavior: Flickable.StopAtBounds
                                            clip: true
                                            delegate: Rectangle {
                                                id: vr
                                                required property var modelData
                                                readonly property bool sel: String(modelData.name) === String(root.val("edge.voice"))
                                                width: vlist.width - 10; height: 38; radius: 10
                                                color: sel ? "#383ddc84" : (vma.containsMouse ? "#12ffffff" : "transparent")
                                                Behavior on color { ColorAnimation { duration: 120 } }
                                                Text {
                                                    x: 12; anchors.verticalCenter: parent.verticalCenter
                                                    text: String(modelData.name).split("-").slice(2).join("-").replace("Neural", "")
                                                    color: vr.sel ? root.verde1 : root.txt
                                                    font.family: root.fuenteMed; font.pixelSize: 13
                                                }
                                                Text {
                                                    anchors.verticalCenter: parent.verticalCenter
                                                    anchors.right: parent.right; anchors.rightMargin: 12
                                                    readonly property string reg: String(modelData.locale).split("-")[1]
                                                    text: (root.regiones[reg] !== undefined ? root.regiones[reg] : reg)
                                                        + " · " + (modelData.gender === "Female" ? "mujer" : "hombre")
                                                    color: root.txtMut; font.family: root.fuente; font.pixelSize: 12
                                                }
                                                MouseArea { id: vma; anchors.fill: parent; hoverEnabled: true
                                                    cursorShape: Qt.PointingHandCursor
                                                    onClicked: ctl.set("edge.voice", String(modelData.name)) }
                                            }
                                        }
                                        Text {
                                            anchors.centerIn: parent
                                            visible: edgeCard.shown.length === 0
                                            text: "Ninguna voz coincide."
                                            color: root.txtMut; font.family: root.fuente; font.pixelSize: 13
                                        }
                                        Rectangle {   // barra de desplazamiento
                                            visible: vlist.contentHeight > vlist.height
                                            anchors.right: parent.right; anchors.rightMargin: 2
                                            width: 3; radius: 2; color: "#40ffffff"
                                            y: 4 + (vlist.height - height) * (vlist.contentY / Math.max(1, vlist.contentHeight - vlist.height))
                                            height: Math.max(24, vlist.height * vlist.height / Math.max(1, vlist.contentHeight))
                                        }
                                    }
                                }
                            }
                            SRow {
                                visible: ctl.voicesState === "loading" || ctl.voicesState === "idle"
                                label: "Trayendo la lista de voces…"
                                hint: "Necesita internet."
                            }
                            SRow {
                                stacked: true
                                visible: ctl.voicesState === "error"
                                label: "No pude traer la lista"
                                hint: ctl.voicesError
                                hintColor: root.aviso
                                Row {
                                    spacing: 8
                                    Field { key: "edge.voice"; width: 320; placeholder: "es-AR-ElenaNeural" }
                                    Btn { label: "Reintentar"; onClicked: ctl.retryVoices() }
                                }
                            }
                        }
                        // --- voz de OpenAI / programa local: se escribe
                        Card {
                            visible: root.provider() !== "edge"
                            title: "Voz"
                            SRow {
                                label: "Nombre de la voz"
                                hint: root.provider() === "openai" ? "En OpenAI: alloy, ash, coral, nova, onyx… En un servidor propio, la que ofrezca."
                                                                    : "Es el texto que reemplaza a {voice} en los argumentos del programa."
                                Field { key: root.provider() === "openai" ? "openai.voice" : "command.voice"; width: 220 }
                            }
                        }
                        Card {
                            title: "Reproducción"
                            SRow {
                                label: "Velocidad"
                                Slide { key: "tts.speed"; from: 0.5; to: 2.0; step: 0.05; decimals: 2; suffix: "×" }
                            }
                            SRow {
                                label: "Volumen"
                                Slide { key: "tts.volume"; from: 0; to: 100; step: 1; decimals: 0; suffix: " %" }
                            }
                        }
                        Card {
                            title: "Probar"
                            SRow {
                                label: "Escuchar cómo suena con lo de arriba"
                                hint: ctl.testMessage !== "" ? ctl.testMessage : "No hace falta guardar antes: prueba lo que ves."
                                hintColor: ctl.testMessage !== "" && !ctl.testing ? root.critico : root.txtMut
                                Btn { label: ctl.testing ? "Detener" : "Probar voz"; primary: !ctl.testing
                                    onClicked: ctl.testVoice() }
                            }
                        }
                        Card {
                            title: "Qué se lee"
                            SRow { label: "Quitar los símbolos de Markdown"
                                hint: "#, *, `, [texto](enlace): que no los deletree."
                                toggleKey: "text.strip_markdown"
                                Toggle { key: "text.strip_markdown" } }
                            SRow { label: "Leer las direcciones web completas"
                                hint: "Apagado, dice «enlace» en vez de https://…"
                                toggleKey: "text.read_urls"
                                Toggle { key: "text.read_urls" } }
                        }
                    }

                    // ====================================================== MODELO / API
                    Column {
                        width: parent.width; spacing: 20
                        visible: root.seccion === "api"
                        Card {
                            visible: root.provider() !== "openai"
                            SRow {
                                label: root.provider() === "edge" ? "Ahora la voz es la de Microsoft Edge"
                                                                   : "Ahora la voz es un programa local"
                                hint: "Estos datos se usan sólo con el motor «API compatible con OpenAI»."
                                hintColor: root.aviso
                                Btn { label: "Usar la API"; onClicked: ctl.set("tts.provider", "openai") }
                            }
                        }
                        Card {
                            title: "Servicio"
                            SRow {
                                label: "Dirección base"
                                hint: "Termina en /v1 y no incluye /audio/speech."
                                Field { key: "openai.base_url"; width: 300; placeholder: "https://api.openai.com/v1" }
                            }
                            SRow {
                                label: "Modelo"
                                hint: "gpt-4o-mini-tts, tts-1, tts-1-hd, kokoro… el que acepte tu servidor."
                                Field { key: "openai.model"; width: 300; placeholder: "gpt-4o-mini-tts" }
                            }
                            SRow {
                                label: "Indicaciones de estilo"
                                hint: "Sólo gpt-4o-mini-tts. Ej.: «Hablá tranquilo y claro»."
                                Field { key: "openai.instructions"; width: 300 }
                            }
                        }
                        Card {
                            title: "Clave de la API"
                            SRow {
                                stacked: true
                                label: ctl.keyStored ? "Hay una clave guardada" : "Todavía no guardaste una clave"
                                hint: !ctl.keyAvailable
                                    ? "Este sistema no tiene Administrador de credenciales: usá la variable de entorno de abajo."
                                    : (ctl.keyStored ? "Está en el Administrador de credenciales de Windows, cifrada con tu cuenta. No se escribe en el config.toml."
                                                     : "Se guarda en el Administrador de credenciales de Windows, nunca en el config.toml.")
                                hintColor: ctl.keyStored ? root.okc : root.txtMut
                                Row {
                                    spacing: 8
                                    visible: ctl.keyAvailable
                                    Field { id: keyField; width: 300; password: true; placeholder: "sk-…"
                                        onSubmitted: (t) => { ctl.saveApiKey(t); keyField.clear() } }
                                    Btn { label: "Guardar clave"; primary: true; enabled: keyField.text.trim() !== ""
                                        onClicked: { ctl.saveApiKey(keyField.text); keyField.clear() } }
                                    Btn { label: "Borrar"; danger: true; visible: ctl.keyStored
                                        onClicked: ctl.removeApiKey() }
                                }
                            }
                            SRow {
                                label: "Variable de entorno (alternativa)"
                                hint: "Si no hay clave guardada, AltR busca la clave en esta variable. Vacío = servidor sin clave."
                                Field { key: "openai.api_key_env"; width: 220; placeholder: "OPENAI_API_KEY" }
                            }
                        }
                    }

                    // ====================================================== OVERLAY
                    Column {
                        width: parent.width; spacing: 20
                        visible: root.seccion === "overlay"
                        Card {
                            title: "Vista previa"
                            Item {
                                width: parent.width; height: pvw.height + 56
                                Preview { id: pvw; x: 12; y: 12; width: parent.width - 24 }
                                Text {
                                    x: 16; y: pvw.height + 24; width: parent.width - 32
                                    text: (root.val("overlay.enabled") === true
                                           ? "Tocá la pantalla para elegir dónde aparece: "
                                           : "El overlay está apagado. Posición: ")
                                        + String(root.posNombres[String(root.val("overlay.position"))]).toLowerCase() + "."
                                    color: root.txtMut; font.family: root.fuente; font.pixelSize: 12
                                }
                            }
                        }
                        Card {
                            title: "Cápsula"
                            SRow { label: "Mostrar la cápsula al leer"
                                hint: "Apagada, la lectura funciona igual."
                                toggleKey: "overlay.enabled"
                                Toggle { key: "overlay.enabled" } }
                            SRow {
                                label: "Opacidad del fondo"
                                Slide { key: "overlay.opacity"; from: 0.3; to: 1.0; step: 0.025; decimals: 0
                                    suffix: " %"; scaleFactor: 100 }
                            }
                            SRow {
                                label: "Tamaño de la letra"
                                Slide { key: "overlay.font_size"; from: 12; to: 28; step: 1; decimals: 0; suffix: " px" }
                            }
                            SRow {
                                stacked: true
                                label: "En qué monitor"
                                Chips {
                                    width: 520
                                    model: ctl.monitorOptions
                                    current: String(root.val("overlay.monitor"))
                                    onPicked: (v) => ctl.set("overlay.monitor", v)
                                }
                            }
                        }
                    }

                    // ====================================================== GENERAL
                    Column {
                        width: parent.width; spacing: 20
                        visible: root.seccion === "general"
                        Card {
                            title: "Inicio y avisos"
                            SRow { label: "Iniciar AltR con Windows"
                                hint: ctl.canAutostart ? "" : "Sólo disponible en Windows."
                                enabled: ctl.canAutostart
                                toggleKey: ctl.canAutostart ? "app.autostart" : ""
                                Toggle { key: "app.autostart"; enabled: ctl.canAutostart } }
                            SRow { label: "Avisos de la bandeja"
                                hint: "Un globo cuando algo falla (por ejemplo, sin internet)."
                                toggleKey: "general.notifications"
                                Toggle { key: "general.notifications" } }
                            SRow { label: "Avisarme cuando haya una versión nueva"
                                hint: "Mira GitHub una vez por día al arrancar. No instala nada solo."
                                toggleKey: "general.check_updates"
                                Toggle { key: "general.check_updates" } }
                        }
                        Card {
                            title: "Versión"
                            SRow {
                                label: "Versión instalada: " + ctl.version
                                hint: ctl.updateState === "available" ? "Hay una versión nueva: " + ctl.latestVersion + "."
                                    : (ctl.updateState === "none" ? "Tenés la última versión."
                                    : (ctl.updateState === "checking" ? "Buscando…" : ctl.updateMessage))
                                hintColor: ctl.updateState === "available" ? root.verde1
                                    : (ctl.updateState === "error" ? root.critico
                                    : (ctl.updateState === "none" ? root.okc : root.txtMut))
                                Row {
                                    spacing: 8
                                    Btn { label: "Ver novedades"; visible: ctl.updateState === "available"
                                        onClicked: ctl.openReleases() }
                                    Btn { label: "Actualizar"; primary: true
                                        visible: ctl.updateState === "available" && ctl.canUpdate
                                        onClicked: ctl.installUpdate() }
                                    Btn { label: ctl.updateState === "checking" ? "Buscando…" : "Buscar actualizaciones"
                                        visible: ctl.updateState !== "available"
                                        enabled: ctl.updateState !== "checking" && ctl.updateState !== "installing"
                                        onClicked: ctl.checkUpdates() }
                                }
                            }
                        }
                        Card {
                            title: "Archivos"
                            SRow {
                                label: "config.toml"
                                hint: ctl.configPath
                                Btn { label: "Abrir config.toml"; onClicked: ctl.openConfig() }
                            }
                        }
                        Note {
                            text: "Todo lo que no está en esta ventana (programas donde no se manda Ctrl+C, límite de caracteres, "
                                + "pronunciación, tono) se edita en el config.toml; al guardar acá se conservan sus comentarios."
                        }
                    }
                }

                Rectangle {   // barra de desplazamiento
                    visible: flick.contentHeight > flick.height
                    anchors.right: parent.right; anchors.rightMargin: 6
                    width: 4; radius: 2; color: "#33ffffff"
                    y: (flick.height - height) * (flick.contentY / Math.max(1, flick.contentHeight - flick.height))
                    height: Math.max(32, flick.height * flick.height / Math.max(1, flick.contentHeight))
                }
            }

            // ------------------------------------------------ pie: estado + Guardar
            Rectangle { anchors.top: flick.bottom; x: root.pad; width: parent.width - 2 * root.pad; height: 1; color: root.divC }
            Item {
                x: root.pad; y: parent.height - root.footH; width: parent.width - 2 * root.pad; height: root.footH
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width - 236
                    wrapMode: Text.WordWrap; maximumLineCount: 2; elide: Text.ElideRight
                    font.family: root.fuente; font.pixelSize: 12
                    text: ctl.error !== "" ? ctl.error
                        : (root.closeArmed ? "Hay cambios sin guardar. Tocá la X de nuevo para descartarlos."
                        : (ctl.status !== "" ? ctl.status
                        : (ctl.dirty ? "Hay cambios sin guardar." : "")))
                    color: ctl.error !== "" ? root.critico
                        : (root.closeArmed ? root.aviso : (ctl.status !== "" ? root.okc : root.txtMut))
                }
                Row {
                    anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                    spacing: 8
                    Btn { label: "Descartar"; enabled: ctl.dirty; onClicked: ctl.revert() }
                    Btn { label: "Guardar y aplicar"; primary: true
                        enabled: ctl.dirty && ctl.error === ""
                        onClicked: ctl.save() }
                }
            }
        }
    }

    onSeccionChanged: { flick.contentY = 0; secFade.restart() }
}
