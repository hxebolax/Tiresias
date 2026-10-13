"""Roles y estados de los objetos accesibles con sus nombres en español."""

from __future__ import annotations

import enum

from ..i18n import _


class Role(enum.IntEnum):
	UNKNOWN = 0
	WINDOW = 1
	TITLEBAR = 2
	PANE = 3
	DIALOG = 4
	CHECKBOX = 5
	RADIOBUTTON = 6
	STATICTEXT = 7
	EDITABLETEXT = 8
	BUTTON = 9
	MENUBAR = 10
	MENUITEM = 11
	POPUPMENU = 12
	COMBOBOX = 13
	LIST = 14
	LISTITEM = 15
	GRAPHIC = 16
	HELPBALLOON = 17
	TOOLTIP = 18
	LINK = 19
	TREEVIEW = 20
	TREEVIEWITEM = 21
	TAB = 22
	TABCONTROL = 23
	SLIDER = 24
	PROGRESSBAR = 25
	SCROLLBAR = 26
	STATUSBAR = 27
	TABLE = 28
	TABLECELL = 29
	TABLECOLUMN = 30
	TABLEROW = 31
	TABLECOLUMNHEADER = 32
	TABLEROWHEADER = 33
	FRAME = 34
	TOOLBAR = 35
	DROPDOWNBUTTON = 36
	CLOCK = 37
	SEPARATOR = 38
	FORM = 39
	HEADING = 40
	HEADING1 = 41
	HEADING2 = 42
	HEADING3 = 43
	HEADING4 = 44
	HEADING5 = 45
	HEADING6 = 46
	PARAGRAPH = 47
	BLOCKQUOTE = 48
	TABLEHEADER = 49
	TABLEBODY = 50
	TABLEFOOTER = 51
	DOCUMENT = 52
	ANIMATION = 53
	APPLICATION = 54
	BOX = 55
	GROUPING = 56
	PROPERTYPAGE = 57
	CANVAS = 58
	CAPTION = 59
	CHECKMENUITEM = 60
	DATEEDITOR = 61
	ICON = 62
	DIRECTORYPANE = 63
	EMBEDDEDOBJECT = 64
	ENDNOTE = 65
	FOOTER = 66
	FOOTNOTE = 67
	GLASSPANE = 68
	HEADER = 69
	IMAGEMAP = 70
	INPUTWINDOW = 71
	LABEL = 72
	NOTE = 73
	PAGE = 74
	RADIOMENUITEM = 75
	LAYEREDPANE = 76
	REDUNDANTOBJECT = 77
	ROOTPANE = 78
	EDITBAR = 79
	TERMINAL = 81
	RICHEDIT = 82
	RULER = 83
	SCROLLPANE = 84
	SECTION = 85
	SHAPE = 86
	SPLITPANE = 87
	VIEWPORT = 88
	TEAROFFMENU = 89
	TEXTFRAME = 90
	TOGGLEBUTTON = 91
	BORDER = 92
	CARET = 93
	CHARACTER = 94
	CHART = 95
	CURSOR = 96
	DIAGRAM = 97
	DIAL = 98
	DROPLIST = 99
	SPLITBUTTON = 100
	MENUBUTTON = 101
	DROPDOWNBUTTONGRID = 102
	MATH = 103
	EQUATION = 104
	GRIP = 105
	HOTKEYFIELD = 106
	INDICATOR = 107
	SPINBUTTON = 108
	SOUND = 109
	WHITESPACE = 110
	TREEVIEWBUTTON = 111
	IPADDRESS = 112
	DESKTOPICON = 113
	INTERNALFRAME = 115
	DESKTOPPANE = 116
	OPTIONPANE = 117
	COLORCHOOSER = 118
	FILECHOOSER = 119
	FILLER = 120
	MENU = 121
	PANEL = 122
	PASSWORDEDIT = 123
	FONTCHOOSER = 124
	LINE = 125
	FONTNAME = 126
	FONTSIZE = 127
	BOLD = 128
	ITALIC = 129
	UNDERLINE = 130
	FGCOLOR = 131
	BGCOLOR = 132
	SUPERSCRIPT = 133
	SUBSCRIPT = 134
	STYLE = 135
	INDENT = 136
	ALIGNMENT = 137
	ALERT = 138
	DATAGRID = 139
	DATAITEM = 140
	HEADERITEM = 141
	THUMB = 142
	CALENDAR = 143
	VIDEO = 144
	AUDIO = 145
	CHARTELEMENT = 146
	DELETED_CONTENT = 147
	INSERTED_CONTENT = 148
	LANDMARK = 149
	ARTICLE = 150
	REGION = 151
	FIGURE = 152
	MARKED_CONTENT = 153
	BULLET = 154
	SUGGESTION = 155
	DEFINITION = 156
	COMMENT = 157
	SWITCH = 158
	SPLITBUTTON_SECTION = 159
	SEMANTICZOOM = 160
	APPBAR = 161
	CUSTOM = 162
	NOTIFICATION = 163


ROLE_LABELS: dict[Role, str] = {
	Role.UNKNOWN: _("desconocido"),
	Role.WINDOW: _("ventana"),
	Role.TITLEBAR: _("barra de título"),
	Role.PANE: _("panel"),
	Role.DIALOG: _("diálogo"),
	Role.CHECKBOX: _("casilla de verificación"),
	Role.RADIOBUTTON: _("botón de opción"),
	Role.STATICTEXT: _("texto"),
	Role.EDITABLETEXT: _("edición"),
	Role.BUTTON: _("botón"),
	Role.MENUBAR: _("barra de menú"),
	Role.MENUITEM: _("elemento de menú"),
	Role.POPUPMENU: _("menú"),
	Role.COMBOBOX: _("cuadro combinado"),
	Role.LIST: _("lista"),
	Role.LISTITEM: _("elemento de lista"),
	Role.GRAPHIC: _("gráfico"),
	Role.HELPBALLOON: _("globo de ayuda"),
	Role.TOOLTIP: _("información sobre herramienta"),
	Role.LINK: _("enlace"),
	Role.TREEVIEW: _("vista de árbol"),
	Role.TREEVIEWITEM: _("elemento de árbol"),
	Role.TAB: _("pestaña"),
	Role.TABCONTROL: _("control de pestañas"),
	Role.SLIDER: _("control deslizante"),
	Role.PROGRESSBAR: _("barra de progreso"),
	Role.SCROLLBAR: _("barra de desplazamiento"),
	Role.STATUSBAR: _("barra de estado"),
	Role.TABLE: _("tabla"),
	Role.TABLECELL: _("celda"),
	Role.TABLECOLUMN: _("columna"),
	Role.TABLEROW: _("fila"),
	Role.TABLECOLUMNHEADER: _("encabezado de columna"),
	Role.TABLEROWHEADER: _("encabezado de fila"),
	Role.FRAME: _("marco"),
	Role.TOOLBAR: _("barra de herramientas"),
	Role.DROPDOWNBUTTON: _("botón desplegable"),
	Role.CLOCK: _("reloj"),
	Role.SEPARATOR: _("separador"),
	Role.FORM: _("formulario"),
	Role.HEADING: _("encabezado"),
	Role.HEADING1: _("encabezado de nivel 1"),
	Role.HEADING2: _("encabezado de nivel 2"),
	Role.HEADING3: _("encabezado de nivel 3"),
	Role.HEADING4: _("encabezado de nivel 4"),
	Role.HEADING5: _("encabezado de nivel 5"),
	Role.HEADING6: _("encabezado de nivel 6"),
	Role.PARAGRAPH: _("párrafo"),
	Role.BLOCKQUOTE: _("cita"),
	Role.TABLEHEADER: _("encabezado de tabla"),
	Role.TABLEBODY: _("cuerpo de tabla"),
	Role.TABLEFOOTER: _("pie de tabla"),
	Role.DOCUMENT: _("documento"),
	Role.ANIMATION: _("animación"),
	Role.APPLICATION: _("aplicación"),
	Role.BOX: _("cuadro"),
	Role.GROUPING: _("agrupación"),
	Role.PROPERTYPAGE: _("página de propiedades"),
	Role.CANVAS: _("lienzo"),
	Role.CAPTION: _("leyenda"),
	Role.CHECKMENUITEM: _("elemento de menú de verificación"),
	Role.DATEEDITOR: _("editor de fecha"),
	Role.ICON: _("icono"),
	Role.DIRECTORYPANE: _("panel de directorio"),
	Role.EMBEDDEDOBJECT: _("objeto incrustado"),
	Role.ENDNOTE: _("nota al final"),
	Role.FOOTER: _("pie"),
	Role.FOOTNOTE: _("nota al pie"),
	Role.GLASSPANE: _("panel de cristal"),
	Role.HEADER: _("cabecera"),
	Role.IMAGEMAP: _("mapa de imagen"),
	Role.INPUTWINDOW: _("ventana de entrada"),
	Role.LABEL: _("etiqueta"),
	Role.NOTE: _("nota"),
	Role.PAGE: _("página"),
	Role.RADIOMENUITEM: _("elemento de menú de opción"),
	Role.LAYEREDPANE: _("panel en capas"),
	Role.REDUNDANTOBJECT: _("objeto redundante"),
	Role.ROOTPANE: _("panel raíz"),
	Role.EDITBAR: _("barra de edición"),
	Role.TERMINAL: _("terminal"),
	Role.RICHEDIT: _("edición enriquecida"),
	Role.RULER: _("regla"),
	Role.SCROLLPANE: _("panel de desplazamiento"),
	Role.SECTION: _("sección"),
	Role.SHAPE: _("forma"),
	Role.SPLITPANE: _("panel dividido"),
	Role.VIEWPORT: _("vista"),
	Role.TEAROFFMENU: _("menú desprendible"),
	Role.TEXTFRAME: _("marco de texto"),
	Role.TOGGLEBUTTON: _("botón de alternar"),
	Role.BORDER: _("borde"),
	Role.CARET: _("cursor"),
	Role.CHARACTER: _("carácter"),
	Role.CHART: _("gráfico estadístico"),
	Role.CURSOR: _("cursor"),
	Role.DIAGRAM: _("diagrama"),
	Role.DIAL: _("dial"),
	Role.DROPLIST: _("lista desplegable"),
	Role.SPLITBUTTON: _("botón dividido"),
	Role.MENUBUTTON: _("botón de menú"),
	Role.DROPDOWNBUTTONGRID: _("cuadrícula de botón desplegable"),
	Role.MATH: _("matemáticas"),
	Role.EQUATION: _("ecuación"),
	Role.GRIP: _("asa"),
	Role.HOTKEYFIELD: _("campo de tecla rápida"),
	Role.INDICATOR: _("indicador"),
	Role.SPINBUTTON: _("botón de giro"),
	Role.SOUND: _("sonido"),
	Role.WHITESPACE: _("espacio en blanco"),
	Role.TREEVIEWBUTTON: _("botón de vista de árbol"),
	Role.IPADDRESS: _("dirección IP"),
	Role.DESKTOPICON: _("icono de escritorio"),
	Role.INTERNALFRAME: _("marco interno"),
	Role.DESKTOPPANE: _("escritorio"),
	Role.OPTIONPANE: _("panel de opciones"),
	Role.COLORCHOOSER: _("selector de color"),
	Role.FILECHOOSER: _("selector de archivos"),
	Role.FILLER: _("relleno"),
	Role.MENU: _("menú"),
	Role.PANEL: _("panel"),
	Role.PASSWORDEDIT: _("edición de contraseña"),
	Role.FONTCHOOSER: _("selector de fuente"),
	Role.LINE: _("línea"),
	Role.ALERT: _("alerta"),
	Role.DATAGRID: _("cuadrícula de datos"),
	Role.DATAITEM: _("elemento de datos"),
	Role.HEADERITEM: _("elemento de encabezado"),
	Role.THUMB: _("control de posición"),
	Role.CALENDAR: _("calendario"),
	Role.VIDEO: _("vídeo"),
	Role.AUDIO: _("audio"),
	Role.CHARTELEMENT: _("elemento de gráfico"),
	Role.DELETED_CONTENT: _("eliminado"),
	Role.INSERTED_CONTENT: _("insertado"),
	Role.LANDMARK: _("punto de referencia"),
	Role.ARTICLE: _("artículo"),
	Role.REGION: _("región"),
	Role.FIGURE: _("figura"),
	Role.MARKED_CONTENT: _("resaltado"),
	Role.BULLET: _("viñeta"),
	Role.SUGGESTION: _("sugerencia"),
	Role.DEFINITION: _("definición"),
	Role.COMMENT: _("comentario"),
	Role.SWITCH: _("interruptor"),
	Role.SPLITBUTTON_SECTION: _("sección de botón dividido"),
	Role.SEMANTICZOOM: _("zoom semántico"),
	Role.APPBAR: _("barra de aplicación"),
	Role.CUSTOM: _("personalizado"),
	Role.NOTIFICATION: _("notificación"),
}

# Abreviaturas para braille.
ROLE_BRAILLE: dict[Role, str] = {
	Role.BUTTON: "btn",
	Role.CHECKBOX: "chk",
	Role.RADIOBUTTON: "rbtn",
	Role.EDITABLETEXT: "edt",
	Role.PASSWORDEDIT: "edt pwd",
	Role.COMBOBOX: "cbo",
	Role.LIST: "lst",
	Role.LISTITEM: "",
	Role.LINK: "lnk",
	Role.GRAPHIC: "gra",
	Role.MENUITEM: "mnuitm",
	Role.MENU: "mnu",
	Role.POPUPMENU: "mnu",
	Role.MENUBAR: "mnubar",
	Role.TAB: "tab",
	Role.TABCONTROL: "tabctl",
	Role.TREEVIEW: "tv",
	Role.TREEVIEWITEM: "tvitem",
	Role.DIALOG: "dlg",
	Role.HEADING: "h",
	Role.TABLE: "tbl",
	Role.SLIDER: "sldr",
	Role.PROGRESSBAR: "prgbar",
	Role.TOOLBAR: "tlbar",
	Role.STATUSBAR: "stbar",
	Role.DOCUMENT: "doc",
	Role.GROUPING: "grp",
	Role.SPLITBUTTON: "splbtn",
	Role.TOGGLEBUTTON: "tgbtn",
	Role.DATAGRID: "grid",
	Role.DATAITEM: "",
	Role.LANDMARK: "lmk",
	Role.ARTICLE: "art",
	Role.REGION: "rgn",
	Role.SWITCH: "swt",
}


def roleLabel(role: Role) -> str:
	return ROLE_LABELS.get(role, "")


class State(enum.IntEnum):
	UNAVAILABLE = 1
	FOCUSED = 2
	SELECTED = 3
	BUSY = 4
	PRESSED = 5
	CHECKED = 6
	HALFCHECKED = 7
	READONLY = 8
	EXPANDED = 9
	COLLAPSED = 10
	INVISIBLE = 11
	VISITED = 12
	LINKED = 13
	HASPOPUP = 14
	PROTECTED = 15
	REQUIRED = 16
	DEFUNCT = 17
	INVALID_ENTRY = 18
	MODAL = 19
	AUTOCOMPLETE = 20
	MULTILINE = 21
	ICONIFIED = 22
	OFFSCREEN = 23
	SELECTABLE = 24
	FOCUSABLE = 25
	CLICKABLE = 26
	EDITABLE = 27
	CHECKABLE = 28
	DRAGGABLE = 29
	DRAGGING = 30
	DROPTARGET = 31
	SORTED = 32
	SORTED_ASCENDING = 33
	SORTED_DESCENDING = 34
	HASLONGDESC = 35
	PINNED = 36
	HASFORMULA = 37
	HASCOMMENT = 38
	OBSCURED = 39
	CROPPED = 40
	OVERFLOWING = 41
	UNLOCKED = 42
	HAS_ARIA_DETAILS = 43
	HASNOTE = 44
	INDETERMINATE = 45
	HALF_PRESSED = 46
	ON = 47
	MULTISELECTABLE = 48


STATE_LABELS: dict[State, str] = {
	State.UNAVAILABLE: _("no disponible"),
	State.FOCUSED: _("con foco"),
	State.SELECTED: _("seleccionado"),
	State.BUSY: _("ocupado"),
	State.PRESSED: _("pulsado"),
	State.CHECKED: _("marcado"),
	State.HALFCHECKED: _("parcialmente marcado"),
	State.READONLY: _("solo lectura"),
	State.EXPANDED: _("expandido"),
	State.COLLAPSED: _("contraído"),
	State.INVISIBLE: _("invisible"),
	State.VISITED: _("visitado"),
	State.LINKED: _("enlazado"),
	State.HASPOPUP: _("submenú"),
	State.PROTECTED: _("protegido"),
	State.REQUIRED: _("obligatorio"),
	State.DEFUNCT: _("no existe"),
	State.INVALID_ENTRY: _("entrada no válida"),
	State.MODAL: _("modal"),
	State.AUTOCOMPLETE: _("con autocompletado"),
	State.MULTILINE: _("multilínea"),
	State.ICONIFIED: _("minimizado"),
	State.OFFSCREEN: _("fuera de pantalla"),
	State.SELECTABLE: _("seleccionable"),
	State.FOCUSABLE: _("enfocable"),
	State.CLICKABLE: _("pulsable"),
	State.EDITABLE: _("editable"),
	State.CHECKABLE: _("marcable"),
	State.DRAGGABLE: _("arrastrable"),
	State.DRAGGING: _("arrastrando"),
	State.DROPTARGET: _("destino de soltar"),
	State.SORTED: _("ordenado"),
	State.SORTED_ASCENDING: _("orden ascendente"),
	State.SORTED_DESCENDING: _("orden descendente"),
	State.HASLONGDESC: _("con descripción larga"),
	State.PINNED: _("anclado"),
	State.HASFORMULA: _("con fórmula"),
	State.HASCOMMENT: _("con comentario"),
	State.OBSCURED: _("oculto"),
	State.CROPPED: _("recortado"),
	State.OVERFLOWING: _("desbordado"),
	State.UNLOCKED: _("desbloqueado"),
	State.HAS_ARIA_DETAILS: _("con detalles"),
	State.HASNOTE: _("con nota"),
	State.INDETERMINATE: _("indeterminado"),
	State.HALF_PRESSED: _("parcialmente pulsado"),
	State.ON: _("activado"),
	State.MULTISELECTABLE: _("selección múltiple"),
}

#: Etiquetas cuando un estado está ausente pero es relevante.
NEGATIVE_STATE_LABELS: dict[State, str] = {
	State.SELECTED: _("no seleccionado"),
	State.CHECKED: _("no marcado"),
	State.PRESSED: _("no pulsado"),
	State.ON: _("desactivado"),
}


def stateLabel(state: State) -> str:
	return STATE_LABELS.get(state, "")


HEADING_ROLES = {Role.HEADING, Role.HEADING1, Role.HEADING2, Role.HEADING3, Role.HEADING4, Role.HEADING5, Role.HEADING6}

#: Roles cuyo nombre no se anuncia porque coincide con su contenido.
ROLES_WITH_CONTENT_AS_NAME = {Role.LINK, Role.HEADING, Role.PARAGRAPH, Role.BUTTON, Role.LISTITEM, Role.TABLECELL}

#: Roles que no se anuncian (solo su nombre/contenido).
SILENT_ROLES = {
	Role.UNKNOWN,
	Role.STATICTEXT,
	Role.PANE,
	Role.PANEL,
	Role.WINDOW,
	Role.APPLICATION,
	Role.SECTION,
	Role.PARAGRAPH,
	Role.FILLER,
	Role.REDUNDANTOBJECT,
	Role.CUSTOM,
	Role.TEXTFRAME,
	Role.WHITESPACE,
	Role.LABEL,
}

#: Roles editables que reciben eco de teclado y lectura por cursor.
EDITABLE_ROLES = {Role.EDITABLETEXT, Role.PASSWORDEDIT, Role.DOCUMENT, Role.TERMINAL, Role.RICHEDIT, Role.COMBOBOX}
