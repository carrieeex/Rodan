import re
import png
import StringIO
import base64
from uuid import uuid4

from django.conf import settings
from lxml import etree


class Glyph(object):
    def __init__(self, xml_glyph):
        ids = xml_glyph.find('ids')
        id_element = ids.find('id')
        features = xml_glyph.find('features')  # 'features' element

        if features is not None:
            feature_list = features.getchildren()
            # alternative: feature_list = features.xpath("feature")
        else:
            feature_list = []

        self.uuid = xml_glyph.get('uuid')[1:]
        self.ulx = float(xml_glyph.get('ulx'))
        self.uly = float(xml_glyph.get('uly'))
        self.nrows = float(xml_glyph.get('nrows'))
        self.ncols = float(xml_glyph.get('ncols'))
        self.id_state = ids.get('state')  # When state is UNCLASSIFIED, id_name and id_confidence don't exist in the xml
                                          # so use empty string and -1
        self.id_name = id_element.get('name') if id_element is not None else ""
        self.id_confidence = float(id_element.get('confidence')) if id_element is not None else -1
        self.data = Glyph.base64_png_encode(xml_glyph)
        self.feature_scaling = float(features.get('scaling')) if features is not None else -1

        self.features = {}
        for f in feature_list:
            self.features[f.get('name')] = [float(n) for n in f.text.split()]

        self.url = self.make_url()

    def make_url(self):
        return "{0}/glyph/{1}".format(settings.BASE_URL, self.uuid)

    @classmethod
    def from_file_with_id(cls, xml_file, glyph_id):
        xml = Glyph.xml_from_file(xml_file)

        # Ref: http://www.w3schools.com/xpath/xpath_syntax.asp
        g = xml.xpath("//glyph[@uuid={0}]".format(glyph_id))

        return Glyph(g)

    @classmethod
    def make_uuid(cls):
        return "{0}{1}".format('g', uuid4().hex)

    @classmethod
    def xml_from_file(cls, xml_file):
        parser = etree.XMLParser(resolve_entities=True)

        with open(xml_file, 'r') as f:
            xml = etree.parse(f, parser)

        return xml

    @classmethod
    def xml_from_json(cls, json_glyph):
        glyph_element = etree.Element("glyph",
                                      uly=str(json_glyph['uly']),
                                      ulx=str(json_glyph['ulx']),
                                      nrows=str(json_glyph['nrows']),
                                      ncols=str(json_glyph['ncols']))
        ids_element = etree.SubElement(glyph_element, "ids",
                                       state=json_glyph['id_state'])
        etree.SubElement(ids_element, "id",
                         name=json_glyph['id_name'],
                         confidence=str(json_glyph['id_confidence']))
        data_element = etree.SubElement(glyph_element, "data")
        data_element.text = Glyph.runlength_encode(json_glyph['data'])
        features_element = etree.SubElement(glyph_element, "features",
                                            scaling=str(json_glyph['feature_scaling']))

        for feature in json_glyph['features']:
            f_element = etree.SubElement(features_element, "feature",
                                         name=feature['name'])
            f_element.text = ' '.join([str(v) for v in feature['values']])

        return glyph_element

    @classmethod
    def name_from_xml(cls, xml_glyph):
        try:
            print xml_glyph
            print xml_glyph.find('ids')
            print xml_glyph.find('ids').find('id')
            print xml_glyph.find('ids').find('id').get('name')
            return xml_glyph.find('ids').find('id').get('name')
        except:
            print "name_from_xml returning __unclassified"
            return "__unclassified"

    @classmethod
    def create(cls, json_glyph, xml_file):
        """ Adds a glyph to a file."""
        parser = etree.XMLParser(resolve_entities=True)
        glyph_element = Glyph.xml_from_json(json_glyph)

        with open(xml_file, 'rwb') as f:
            xml = etree.parse(f, parser)
            glyphs = xml.xpath('//glyphs')
            glyphs.append(glyph_element)
            glyphs[:] = sorted(glyphs, key=lambda glyph: Glyph.name_from_xml(glyph))
            f.write(etree.tostring(xml, pretty_print=True, xml_declaration=True, encoding="utf-8"))

    @classmethod
    def update(cls, request_data, xml_file, glyph_id):
        """ Writes a glyph in a file given new data (id_state, id_name, id_confidence)."""
        parser = etree.XMLParser(resolve_entities=True)

        with open(xml_file, 'rwb') as f:
            xml = etree.parse(f, parser)
            glyph = xml.xpath("//glyph[@uuid={0}]".format(glyph_id))
            ids_element = glyph.find('ids')
            id_element = ids_element.find('id')

            for key, value in request_data.iteritems():
                if key is 'id_state':
                    ids_element.set(key, value)
                elif key in ['id_name, id_confidence']:
                    id_element.set(key, value)

            glyphs = xml.xpath("//glyphs")
            glyphs[:] = sorted(glyphs, key=lambda glyph: Glyph.name_from_xml(glyph))

            f.write(etree.tostring(xml, pretty_print=True, xml_declaration=True, encoding="utf-8"))

        # Hmmm... first time I did it I did separate read/writes
        # xml = Glyph.xml_from_file(xml_file)
        # g = xml.xpath("//glyph[@uuid={0}]".format(glyph_id))
        # ids_element = g.find('ids')
        # id_element = ids_element.find('id')

        # for k, v in request_data.iteritems():
        #     if k is 'id_state':
        #         ids_element.set(k, v)
        #     elif k in ['id_name, id_confidence']:
        #         id_element.set(k, v)

        # Glyph.write_xml_to_file(xml, xml_file)

    @classmethod
    def destroy(cls, xml_file, glyph_id):
        parser = etree.XMLParser(resolve_entities=True)

        with open(xml_file, 'rwb') as f:
            xml = etree.parse(f, parser)
            g = xml.xpath("//glyph[@uuid={0}]".format(glyph_id))
            #g.strip_elements('glyph')  # I think it'll detect its parent and remove itself.
                # Try also calling it on the parent and specifying... or just remove the object from the list (xml is a list)
            xml.remove(g)

            f.write(etree.tostring(xml, pretty_print=True, xml_declaration=True, encoding="utf-8"))

    @classmethod
    def base64_png_encode(cls, glyph):
        """ Takes an xpath glyph element and returns a png image of the
        glyph. """
        nrows = int(glyph.get('nrows'))
        ncols = int(glyph.get('ncols'))
        # Make an iterable that yields each row in boxed row flat pixel format:
        #   http://pypng.googlecode.com/svn/trunk/code/png.py
        # Method: Make a list of length nrows * ncols then after make sublists of
        # length ncols.
        pixels = []
        white_or_black = 255  # 255 is white

        for n in re.findall("\d+", glyph.find('data').text):
            pixels.extend([white_or_black] * int(n))
            white_or_black = white_or_black ^ 255  # Toggle between 0 and 255

        png_writer = png.Writer(width=ncols, height=nrows, greyscale=True)
        pixels_2D = []

        for i in xrange(nrows):
            pixels_2D.append(pixels[i*ncols: (i+1)*ncols])  # Index one row of pixels

        # StringIO.StringIO lets you write to strings as files: it gives you a file descriptor.
        # (pypng expects a file descriptor)
        buf = StringIO.StringIO()
        png_writer.write(buf, pixels_2D)
        return base64.b64encode(buf.getvalue())

    @classmethod
    def runlength_encode(cls, base64_encoded_png):
        my_png = base64.b64decode(base64_encoded_png)
        buf = StringIO.StringIO(my_png)
        r = png.Reader(file=buf)  # Note: it gets confused if you don't name the argument
        r_out = r.read_flat()

        runlength_array = []
        previous_pixel = 255
        runlength = 0
        for pixel in r_out[2]:
            if (pixel == previous_pixel):
                runlength += 1
            else:
                runlength_array.append(runlength)
                runlength = 1
                previous_pixel = previous_pixel ^ 255  # Toggle between 0 and 255

        runlength_array.append(runlength)

        if (pixel == 255):
            runlength_array.append(0)
            # the last number must be the runlength of black pixels
            # so this case adds a zero if the bottom right pixel was white

        return ' '.join(map(str, runlength_array))
        # Returns a string containing each integer separated by spaces:
        # The 'map' call converts to an array of strings, then 'join' into one string






### GAMERA XML AS A DICTIONARY ###
# Glyph Object
#{
#    'ulx':
#    'uly':
#    'nrows':
#    'ncols':
#    'ids': {
#            'state':
#             'id': { 'name': 'confidence': }
#            }
#    'data': base64 encoded PNG
#    'feature_scaling':
#    'features': [
#                    {'name': name 'values': [split of text values]}
#                    ...
#                ]
#}

### IDS ###
# ids has a state and an id
# id has a name and a confidence
# I'm pretty sure you can only have one id in an ids thing.
# So why not change it to a single element?
# id: {'state': 'name': 'confidence'}
# Even better: Just fan it back into the glyph object

#{
#    'ulx':
#    'uly':
#    'nrows':
#    'ncols':
#    'id_state':
#    'id_name':
#    'id_confidence':
#    'data': base64 encoded PNG
#    'feature_scaling':
#    'features': [
#                    {'name': name 'values': [split of text values]}
#                    ...
#                ]
#}

# Do I need to write an XML schema and run it against a lot of gamera
# XML to ensure that it all follows my assumptions, especially
#  <ids> only has one <id> child
# I can't imagine a glyph having two states and names and
# confidences... so I don't need to.

# States can be
#  MANUAL AUTOMATIC HEURISTIC UNCLASSIFIED
# Example of unclassified:
#    <glyph uly="628" ulx="783" nrows="5" ncols="15">
#      <ids state="UNCLASSIFIED">
#      </ids>
#      <data>
#        1 13 1 45 1 13 1 0
#      </data>
#    </glyph>
# So, the schema might say
# - Required: ulx, uly, nrows, ncols, ids, data
# - ids is necessary but id is not if ids is UNCLASSIFIED
# - features are optional (along with feature_scaling)


# Glyph Object

### SYMBOLS ###
# There should also be a Symbol object
#<gamera-database version="2.0">
#  <symbols>
#    <symbol name="_group"/>
#    <symbol name="_group._part"/>
#    <symbol name="_group._part.clef.c"/>
#    <symbol name="_group._part.division.final"/>
# It's just a list of names.  Very simple.
# The symbols get saved when you save page glyphs.
# It can honesly just be a 1d array of strings.