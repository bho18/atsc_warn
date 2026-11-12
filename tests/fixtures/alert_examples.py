"""Synthetic alert scenarios, never an original capture or schema-validity claim."""

from xml.sax.saxutils import escape


def cap(
    identifier="demo-alert",
    kind="Alert",
    status="Actual",
    references="",
    sent="2026-11-12T01:00:00Z",
    expires="2026-11-14T01:00:00Z",
):
    refs = f"<references>{escape(references)}</references>" if references else ""
    infos = (
        ""
        if kind == "Cancel"
        else f"""
<info><language>en-US</language><category>Met</category><event>Synthetic flood scenario</event>
<urgency>Immediate</urgency><severity>Severe</severity><certainty>Observed</certainty>
<effective>{sent}</effective>
<expires>{expires}</expires>
<senderName>WarnBridge synthetic demo</senderName>
<headline>DEMO ONLY — Flood warning example</headline>
<description>Synthetic display fixture. No real emergency is being reported.</description>
<instruction>DEMO ONLY: Example instructions appear here. This is not a real warning.</instruction>
<parameter>
<valueName>CMAMtext</valueName>
<value>DEMO ONLY short wireless alert text.</value></parameter>
<parameter>
<valueName>CMAMlongtext</valueName>
<value>DEMO ONLY longer wireless alert text.</value></parameter>
<area><areaDesc>Synthetic polygon area</areaDesc><polygon>36,-87 36,-86 35,-86 36,-87</polygon>
<geocode><valueName>SAME</valueName>
<value>047037</value></geocode></area>
<area><areaDesc>Synthetic circle area</areaDesc><circle>36.1,-86.7 5</circle></area></info>
<info><language>es-US</language><category>Met</category><event>Ejemplo sintético</event>
<urgency>Immediate</urgency><severity>Severe</severity><certainty>Observed</certainty>
<effective>{sent}</effective>
<expires>{expires}</expires>
<headline>SOLO DEMO — Ejemplo de alerta</headline>
<description>Datos sintéticos; no hay una emergencia real.</description>
<instruction>SOLO DEMO: Instrucciones de ejemplo.</instruction>
<area><areaDesc>Área de ejemplo</areaDesc><geocode><valueName>SAME</valueName>
<value>047037</value></geocode>
</area></info>"""
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
<identifier>{escape(identifier)}</identifier><sender>synthetic.warnbridge.example</sender>
<sent>{sent}</sent><status>{escape(status)}</status><msgType>{escape(kind)}</msgType>
<scope>Public</scope>{refs}{infos}</alert>""".encode()


CMAC = b"""<?xml version="1.0" encoding="UTF-8"?>
<CMAC_Alert_Attributes xmlns="cmac:2.0">
<CMAC_protocol_version>2.0</CMAC_protocol_version>
<CMAC_sending_gateway_id>urn:warnbridge:synthetic</CMAC_sending_gateway_id>
<CMAC_message_number>demo-cmac-review</CMAC_message_number>
<CMAC_sent_date_time>2026-11-12T01:00:00Z</CMAC_sent_date_time>
<CMAC_status>Actual</CMAC_status><CMAC_message_type>Alert</CMAC_message_type>
<CMAC_alert_info><CMAC_severity>Severe</CMAC_severity><CMAC_urgency>Immediate</CMAC_urgency>
<CMAC_Alert_Text><CMAC_text_language>en-US</CMAC_text_language>
<CMAC_text_alert_message>
DEMO ONLY - synthetic CMAC text for field review, not an actual warning.
</CMAC_text_alert_message></CMAC_Alert_Text>
<CMAC_Alert_Area><CMAC_area_description>Synthetic CMAC area</CMAC_area_description>
<CMAC_cmas_geocode>047037</CMAC_cmas_geocode></CMAC_Alert_Area>
<CMAC_unknown_extension>Preserve this unknown field.</CMAC_unknown_extension>
</CMAC_alert_info></CMAC_Alert_Attributes>"""
