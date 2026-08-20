"""
Hardened XML parsing for untrusted scenario and map files.

The standard library parsers expand internal entities, which makes a few
hundred bytes of XML enough to exhaust the memory of the process reading it
("billion laughs", quadratic blowup). The checker parses files that arrive over
HTTP from anonymous users, so every parse of untrusted input goes through this
module rather than through ``xml.etree`` or ``xml.sax`` directly.

OpenSCENARIO and OpenDRIVE have no legitimate use for a DOCTYPE, so documents
carrying one are refused outright instead of merely being parsed with entity
expansion turned off. That is a stricter rule than defusedxml's default and it
is the point: it removes the entity machinery from the picture entirely.
"""

from __future__ import annotations

from xml.etree.ElementTree import ParseError

from defusedxml import ElementTree as _element_tree
from defusedxml.common import DefusedXmlException
from defusedxml.sax import make_parser as _make_defused_parser

#: Raised when a document is rejected for what it contains (a DOCTYPE, an
#: entity declaration, an external reference) rather than for being malformed.
#: Re-exported so callers can tell a hostile document from a broken one without
#: importing defusedxml themselves.
UnsafeXmlError = DefusedXmlException

__all__ = ["ParseError", "UnsafeXmlError", "parse", "fromstring", "make_parser"]


def parse(source):
    """
    Parse a file path or file-like object into an ElementTree, safely.

    Args:
        source: Path or open file object holding the XML.
    return: xml.etree.ElementTree.ElementTree instance.
    raises UnsafeXmlError: The document declares a DOCTYPE or an entity.
    raises ParseError: The document is not well-formed XML.
    """
    return _element_tree.parse(source, forbid_dtd=True)


def fromstring(text):
    """
    Parse a string of XML into an Element, safely.

    Args:
        text: XML document as str or bytes.
    return: xml.etree.ElementTree.Element instance.
    raises UnsafeXmlError: The document declares a DOCTYPE or an entity.
    raises ParseError: The document is not well-formed XML.
    """
    return _element_tree.fromstring(text, forbid_dtd=True)


def make_parser():
    """
    Return a SAX parser that refuses DOCTYPEs, entities and external references.

    Args:
        None
    return: Configured xml.sax parser.
    """
    parser = _make_defused_parser()
    parser.forbid_dtd = True
    return parser
