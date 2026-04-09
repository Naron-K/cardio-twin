"""
XML Converter - Bidirectional XML ↔ JSON Utilities
====================================================
Handles all XML conversion for the CardioTwin API:
  - patient_xml_to_dict(): Parse patient XML → sensor data dict
  - dict_to_patient_xml(): Sensor data dict → patient XML string
  - results_to_xml(): Computation results dict → structured XML string
"""

import xml.etree.ElementTree as ET
from typing import Any, Dict
from datetime import datetime


def patient_xml_to_dict(xml_string: str) -> Dict[str, float]:
    """
    Parse a patient XML string and return a dict of sensor values.

    Expected XML format:
        <patient>
          <sensor_data>
            <SBP>120</SBP>
            <DBP>80</DBP>
            ...
          </sensor_data>
        </patient>

    Returns:
        {'SBP': 120.0, 'DBP': 80.0, ...}

    Raises:
        ValueError: If XML is malformed or <sensor_data> block is missing.
    """
    try:
        root = ET.fromstring(xml_string.strip())
    except ET.ParseError as e:
        raise ValueError(f"Malformed XML: {e}")

    sensor_el = root.find("sensor_data")
    if sensor_el is None:
        raise ValueError("Missing <sensor_data> block in patient XML")

    sensor_data: Dict[str, float] = {}
    for child in sensor_el:
        text = child.text
        if text is None or text.strip() == "":
            raise ValueError(f"Sensor '{child.tag}' has no value")
        try:
            sensor_data[child.tag] = float(text.strip())
        except ValueError:
            raise ValueError(f"Sensor '{child.tag}' has non-numeric value: '{text.strip()}'")

    if not sensor_data:
        raise ValueError("<sensor_data> block is empty")

    return sensor_data


def dict_to_patient_xml(sensor_data: Dict[str, float], name: str = "Patient Scenario",
                         description: str = "") -> str:
    """
    Convert a sensor data dictionary to a patient XML string.

    Used when saving current slider state for download.

    Args:
        sensor_data: {'SBP': 120.0, 'DBP': 80.0, ...}
        name: Human-readable scenario name
        description: Optional description for metadata block

    Returns:
        UTF-8 encoded XML string
    """
    root = ET.Element("patient")

    # Metadata block
    meta = ET.SubElement(root, "metadata")
    ET.SubElement(meta, "name").text = name
    ET.SubElement(meta, "description").text = description
    ET.SubElement(meta, "created_at").text = datetime.now().isoformat()

    # Sensor data block
    sensors_el = ET.SubElement(root, "sensor_data")
    for key, value in sensor_data.items():
        ET.SubElement(sensors_el, key).text = str(value)

    return _to_xml_string(root)


def results_to_xml(results: Dict[str, Any], name: str = "Computation Results") -> str:
    """
    Convert a computation results dict (from /api/compute) to a structured XML string.

    Expected results format:
        {
            "sensors": {"SBP": 120, ...},
            "computed": {"MAP": 93.33, "R": 0.012, ...},
            "vectors": {"pressure_state": {"SBP": 0.33, ...}, ...},
            "warnings": ["GATE FAIL: ..."],
            "log": [...]
        }

    Returns:
        UTF-8 encoded XML string suitable for download.
    """
    root = ET.Element("cardiotwin_results")

    # Metadata
    meta = ET.SubElement(root, "metadata")
    ET.SubElement(meta, "name").text = name
    ET.SubElement(meta, "generated_at").text = datetime.now().isoformat()
    ET.SubElement(meta, "version").text = "1.0"

    # Sensor inputs
    if "sensors" in results:
        sensors_el = ET.SubElement(root, "sensor_data")
        for key, value in results["sensors"].items():
            ET.SubElement(sensors_el, key).text = str(value) if value is not None else ""

    # Computed (preliminary) values
    if "computed" in results:
        computed_el = ET.SubElement(root, "computed_values")
        for key, value in results["computed"].items():
            el = ET.SubElement(computed_el, key)
            el.text = f"{value:.4f}" if value is not None else ""

    # Composite vectors
    if "vectors" in results:
        vectors_el = ET.SubElement(root, "composite_vectors")
        for comp_id, vector in results["vectors"].items():
            comp_el = ET.SubElement(vectors_el, "composite", id=comp_id)
            for attr_id, norm_val in vector.items():
                attr_el = ET.SubElement(comp_el, attr_id)
                attr_el.text = f"{norm_val:.4f}" if norm_val is not None else ""

    # Gate warnings
    if "warnings" in results:
        warnings_el = ET.SubElement(root, "gate_warnings")
        for warning in results["warnings"]:
            ET.SubElement(warnings_el, "warning").text = warning

    # Segments (if provided)
    if "segments" in results:
        segs_el = ET.SubElement(root, "segments")
        for seg_id, seg in results["segments"].items():
            seg_el = ET.SubElement(segs_el, "segment", id=seg_id, name=seg.get("name", seg_id))
            ET.SubElement(seg_el, "attributes").text = ", ".join(seg.get("attribute_ids", []))
            ET.SubElement(seg_el, "composites").text = ", ".join(seg.get("composite_ids", []))
            ET.SubElement(seg_el, "functions").text = ", ".join(seg.get("function_ids", []))

    return _to_xml_string(root)


def _to_xml_string(root: ET.Element) -> str:
    """Serialize an ElementTree Element to a pretty-printed XML string."""
    _indent(root)
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def _indent(elem: ET.Element, level: int = 0):
    """Add pretty-print indentation to an XML tree in-place."""
    indent = "\n" + "  " * level
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = indent + "  "
        if not elem.tail or not elem.tail.strip():
            elem.tail = indent
        for child in elem:
            _indent(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = indent
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = indent
