import Quickshell
import Quickshell.Io
import QtQuick
import qs.Commons
import qs.Ui

Item {
  id: root

  property var shell: null
  property var manifest: null
  property bool closingFromHost: false
  property bool opened: false
  property bool loading: false
  property int requestSerial: 0
  property string term: ""
  property string headword: ""
  property string pronunciation: ""
  property string grammar: ""
  property string definition: ""
  property string definitionHtml: ""
  property string url: ""
  property string errorText: ""
  property int catalogCount: 0

  property color background: Color.menu.background
  property color foreground: Color.menu.text
  property color border: Color.menu.border
  property var borderSpec: Border.surfaceSpec("menu", "border", border, Math.max(1, Style.space(2)))
  readonly property int cornerRadius: Style.cornerRadius
  property string fontFamily: Style.font.menuFamily
  property int contentMargin: Style.spacing.panelPadding
  property int contentSpacing: Style.spacing.md
  property int headerGap: Style.spacing.xs
  readonly property string fetchScript: Qt.resolvedUrl("fetch.py").toString().replace("file://", "")

  readonly property string displayTitle: root.term !== "" ? root.term : "Jargon"
  readonly property string displayMeta: {
    var parts = []
    if (root.pronunciation !== "") parts.push(root.pronunciation)
    if (root.grammar !== "") parts.push(root.grammar)
    return parts.join("  ·  ")
  }
  readonly property string bodyHtml: {
    if (root.loading) return "Drawing a random entry…"
    if (root.errorText !== "") return root.escapeHtml(root.errorText)
    if (root.definitionHtml !== "") return root.styleLinks(root.definitionHtml)
    return root.escapeHtml(root.definition)
  }

  function open(payloadJson) {
    root.closingFromHost = false
    root.opened = true
    window.visible = true
    Qt.callLater(function() {
      if (keyCatcher) keyCatcher.forceActiveFocus()
    })
    root.loadRandom()
  }

  function close() {
    root.closingFromHost = true
    root.opened = false
    window.visible = false
    root.closingFromHost = false
  }

  function dismiss() {
    if (root.shell && typeof root.shell.hide === "function")
      root.shell.hide((root.manifest && root.manifest.id) || "jra.jargon")
    else
      root.close()
  }

  function toggle() {
    if (root.opened) root.dismiss()
    else root.open("{}")
  }

  function loadRandom() {
    root.loading = true
    root.errorText = ""
    root.requestSerial += 1
    var serial = root.requestSerial
    if (fetchProc.running) {
      fetchProc.ignoreExit = true
      fetchProc.running = false
    }
    Qt.callLater(function() {
      if (serial !== root.requestSerial) return
      fetchProc.ignoreExit = false
      fetchProc.acceptedSerial = serial
      fetchProc.running = true
    })
  }

  function applyFetch(raw, serial) {
    if (serial !== root.requestSerial) return
    root.loading = false
    var data = null
    try {
      data = JSON.parse(String(raw || "").trim() || "{}")
    } catch (e) {
      root.errorText = "The jargon page came back unreadable."
      return
    }
    if (!data || data.ok !== true) {
      root.errorText = (data && data.error) ? String(data.error) : "Could not fetch a jargon entry."
      return
    }
    root.errorText = ""
    root.term = String(data.term || "")
    root.headword = String(data.headword || "")
    root.pronunciation = String(data.pronunciation || "")
    root.grammar = String(data.grammar || "")
    root.definition = String(data.definition || "")
    root.definitionHtml = String(data.definitionHtml || "")
    root.url = String(data.url || "")
    root.catalogCount = Number(data.count || 0)
    scroller.contentY = 0
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
  }

  function styleLinks(html) {
    var color = String(Color.accent)
    return String(html || "").replace(/<a /g, '<a style="color:' + color + '; text-decoration:underline;" ')
  }

  function openLink(link) {
    var href = String(link || "")
    if (href.indexOf("http://") !== 0 && href.indexOf("https://") !== 0)
      return
    Quickshell.execDetached(["omarchy-launch-browser", href])
  }

  function openSource() {
    root.openLink(root.url)
  }

  function scrollBy(delta) {
    var maxY = Math.max(0, scroller.contentHeight - scroller.height)
    scroller.contentY = Math.max(0, Math.min(maxY, scroller.contentY + delta))
  }

  Process {
    id: fetchProc
    property int acceptedSerial: 0
    property bool ignoreExit: false
    command: ["python3", root.fetchScript]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.applyFetch(text, fetchProc.acceptedSerial)
    }
    onExited: function(exitCode, exitStatus) {
      if (fetchProc.ignoreExit) return
      if (fetchProc.acceptedSerial !== root.requestSerial) return
      if (exitCode !== 0 && root.loading)
        root.applyFetch("", fetchProc.acceptedSerial)
    }
  }

  FloatingWindow {
    id: window
    title: "Jargon"
    color: root.background
    implicitWidth: Style.space(460)
    implicitHeight: Style.space(320)
    minimumSize: Qt.size(280, 180)

    onVisibleChanged: {
      if (visible) {
        root.opened = true
        return
      }
      root.opened = false
      if (!root.closingFromHost && root.shell && typeof root.shell.hide === "function")
        root.shell.hide((root.manifest && root.manifest.id) || "jra.jargon")
    }

    Item {
      id: keyCatcher
      anchors.fill: parent
      focus: true

      Keys.priority: Keys.BeforeItem
      Keys.onPressed: function(event) {
        if (event.key === Qt.Key_Escape) {
          root.dismiss()
          event.accepted = true
        } else if (event.key === Qt.Key_Space || event.key === Qt.Key_N || event.key === Qt.Key_R) {
          root.loadRandom()
          event.accepted = true
        } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
          root.openSource()
          event.accepted = true
        } else if (event.key === Qt.Key_Down || event.key === Qt.Key_PageDown) {
          root.scrollBy(event.key === Qt.Key_PageDown ? 120 : 36)
          event.accepted = true
        } else if (event.key === Qt.Key_Up || event.key === Qt.Key_PageUp) {
          root.scrollBy(event.key === Qt.Key_PageUp ? -120 : -36)
          event.accepted = true
        }
      }

      BorderSurface {
        id: card
        anchors.fill: parent
        radius: root.cornerRadius
        color: root.background
        borderSpec: root.borderSpec
        padding: root.contentMargin

        Item {
          id: header
          anchors.top: parent.top
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.topMargin: card.contentTopInset
          anchors.leftMargin: card.contentLeftInset
          anchors.rightMargin: card.contentRightInset
          height: titleText.implicitHeight + (metaText.visible ? root.headerGap + metaText.implicitHeight : 0)

          Text {
            id: titleText
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            textFormat: Text.PlainText
            text: root.displayTitle
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.heading
            font.bold: true
            wrapMode: Text.Wrap
          }

          Text {
            id: metaText
            anchors.top: titleText.bottom
            anchors.topMargin: root.headerGap
            anchors.left: parent.left
            anchors.right: parent.right
            visible: root.displayMeta !== "" && !root.loading
            textFormat: Text.PlainText
            text: root.displayMeta
            color: Color.muted
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
            wrapMode: Text.Wrap
          }

          MouseArea {
            anchors.fill: parent
            cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
            onPressed: function(mouse) {
              if (mouse.button === Qt.LeftButton)
                window.startSystemMove()
            }
          }
        }

        Text {
          id: hintText
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.bottom: parent.bottom
          anchors.leftMargin: card.contentLeftInset
          anchors.rightMargin: card.contentRightInset
          anchors.bottomMargin: card.contentBottomInset
          textFormat: Text.PlainText
          text: root.loading
            ? "esc close"
            : "drag title to move   click links   space next   enter source   esc close"
          color: Color.muted
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
        }

        Flickable {
          id: scroller
          anchors.top: header.bottom
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.bottom: hintText.top
          anchors.topMargin: root.contentSpacing
          anchors.bottomMargin: root.contentSpacing
          anchors.leftMargin: card.contentLeftInset
          anchors.rightMargin: card.contentRightInset
          clip: true
          contentWidth: width
          contentHeight: bodyText.height
          boundsBehavior: Flickable.StopAtBounds
          flickableDirection: Flickable.VerticalFlick

          Text {
            id: bodyText
            width: scroller.width
            textFormat: Text.RichText
            text: root.bodyHtml
            color: root.errorText !== "" ? Color.urgent : root.foreground
            opacity: root.loading ? 0.58 : 1
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            wrapMode: Text.Wrap
            onLinkActivated: function(link) { root.openLink(link) }

            MouseArea {
              anchors.fill: parent
              acceptedButtons: Qt.NoButton
              hoverEnabled: true
              cursorShape: bodyText.hoveredLink !== "" ? Qt.PointingHandCursor : Qt.ArrowCursor
            }
          }
        }
      }
    }
  }
}
