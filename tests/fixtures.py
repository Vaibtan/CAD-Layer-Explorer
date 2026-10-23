"""Small synthetic PDFs: source semantics are explicit, no private drawing content."""
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import (ArrayObject, BooleanObject, DecodedStreamObject, DictionaryObject,
                           FloatObject, NameObject, NumberObject, TextStringObject)


def dictionary(**items):
    return DictionaryObject({NameObject('/' + key): value for key, value in items.items()})


def stream(writer, content, **items):
    obj = DecodedStreamObject()
    obj.set_data(content)
    obj.update(dictionary(**items))
    return writer._add_object(obj)


def fixture(path, kind='counts'):
    writer = PdfWriter()
    page = writer.add_blank_page(240, 160)
    groups = [writer._add_object(dictionary(Type=NameObject('/OCG'), Name=TextStringObject(name)))
              for name in ['Duplicate', 'Duplicate', 'Empty scope', 'Unused']]
    writer._root_object[NameObject('/OCProperties')] = dictionary(
        OCGs=ArrayObject(groups), D=dictionary(BaseState=NameObject('/ON'), OFF=ArrayObject([groups[1]]), Order=ArrayObject(groups)))
    props = dictionary(A=groups[0], B=groups[1], E=groups[2])
    font = writer._add_object(dictionary(Type=NameObject('/Font'), Subtype=NameObject('/Type1'), BaseFont=NameObject('/Helvetica')))
    image = stream(writer, b'\xff\x00\x00', Type=NameObject('/XObject'), Subtype=NameObject('/Image'),
                   Width=NumberObject(1), Height=NumberObject(1), ColorSpace=NameObject('/DeviceRGB'), BitsPerComponent=NumberObject(8))
    shade = writer._add_object(dictionary(ShadingType=NumberObject(2), ColorSpace=NameObject('/DeviceRGB'),
        Coords=ArrayObject([NumberObject(x) for x in [0, 0, 100, 0]]),
        Function=dictionary(FunctionType=NumberObject(2), Domain=ArrayObject([NumberObject(0), NumberObject(1)]),
                            C0=ArrayObject([NumberObject(0)]*3), C1=ArrayObject([NumberObject(1)]*3), N=NumberObject(1)),
        Extend=ArrayObject([BooleanObject(True),BooleanObject(True)])))
    form = stream(writer, b'10 10 10 10 re f', Type=NameObject('/XObject'), Subtype=NameObject('/Form'),
                  BBox=ArrayObject([NumberObject(x) for x in [0,0,100,100]]))
    outer = stream(writer, b'/Fm Do /Fm Do', Type=NameObject('/XObject'), Subtype=NameObject('/Form'),
                   BBox=ArrayObject([NumberObject(x) for x in [0,0,100,100]]), Resources=dictionary(XObject=dictionary(Fm=form)))
    resources = dictionary(Properties=props, Font=dictionary(F1=font), XObject=dictionary(Im=image, Fm=form, Outer=outer), Shading=dictionary(Sh=shade))
    content = b'/OC /A BDC 0 0 10 10 re B BT /F1 12 Tf 10 30 Td (A) Tj () Tj [12 -3] TJ ET /Im Do /Im Do /Fm Do /Outer Do q 1 0 0 1 20 20 cm BI /W 1 /H 1 /CS /RGB /BPC 8 ID \xff\x00\x00 EI Q /Sh sh EMC /OC /B BDC 100 80 30 30 re f EMC /OC /E BDC EMC'
    if kind == 'base':
        content = b'10 10 20 20 re f /OC /A BDC 100 80 20 20 re f EMC'
    elif kind == 'conditional':
        membership = writer._add_object(dictionary(Type=NameObject('/OCMD'), OCGs=ArrayObject(groups[:2]), P=NameObject('/AllOn')))
        props[NameObject('/M')] = membership
        content = b'/OC /M BDC 10 10 20 20 re f EMC /OC /A BDC /OC /B BDC 50 50 20 20 re f EMC EMC'
    elif kind == 'invisible':
        content = b'/OC /A BDC 1 1 1 rg 10 10 20 20 re f 0 0 0 rg 500 500 20 20 re f q 0 0 0 0 re W n 20 20 20 20 re f Q BT /F1 12 Tf 3 Tr (Invisible) Tj ET EMC'
    elif kind == 'plain':
        del writer._root_object['/OCProperties']
        content = b'10 10 20 20 re f'
    elif kind == 'scan':
        del writer._root_object['/OCProperties']
        content = b'q 200 0 0 140 0 0 cm /Im Do Q'
    elif kind == 'cycle':
        resolve_form = form.get_object()
        resolve_form[NameObject('/Resources')] = dictionary(XObject=dictionary(Fm=form))
        resolve_form.set_data(b'/Fm Do')
        content = b'/OC /A BDC /Fm Do EMC'
    elif kind == 'annotation':
        content = b'/OC /A BDC 10 10 20 20 re f EMC'
        annotation = writer._add_object(dictionary(Type=NameObject('/Annot'), Subtype=NameObject('/Square'),
          Rect=ArrayObject([NumberObject(x) for x in [10,10,30,30]]), OC=groups[1], Contents=TextStringObject('AutoCAD SHX Text')))
        page[NameObject('/Annots')] = ArrayObject([annotation])
    elif kind == 'rotated':
        page[NameObject('/Rotate')] = NumberObject(90)
        page[NameObject('/CropBox')] = ArrayObject([NumberObject(x) for x in [10,10,230,150]])
        content = b'/OC /A BDC 20 20 40 20 re f EMC /OC /B BDC 100 80 20 30 re f EMC'
    elif kind == 'restricted':
        writer._root_object['/OCProperties']['/D'][NameObject('/RBGroups')] = ArrayObject([ArrayObject(groups[:2])])
    page[NameObject('/Resources')] = resources
    page[NameObject('/Contents')] = stream(writer, content)
    if kind == 'encrypted':
        writer.encrypt('secret')
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'wb') as output:
        writer.write(output)
    return Path(path)
