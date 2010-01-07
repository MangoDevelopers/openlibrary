import web
import urllib, urllib2
import simplejson

from infogami.infobase import client
from infogami.utils.view import safeint

from openlibrary.plugins.search.code import SearchProcessor
from openlibrary.plugins.openlibrary import code as ol_code

from utils import get_coverstore_url, MultiDict, parse_toc
import account

class Image:
    def __init__(self, category, id):
        self.category = category
        self.id = id
    
    def url(self, size="M"):
        return "%s/%s/id/%s-%s.jpg" % (get_coverstore_url(), self.category, self.id, size.upper())
        
    def __repr__(self):
        return "<image: %s/%d>" % (self.category, self.id)

def query_coverstore(category, **kw):
    url = "%s/%s/query?%s" % (get_coverstore_url(), category, urllib.urlencode(kw))
    json = urllib.urlopen(url).read()
    return simplejson.loads(json)

class Edition(ol_code.Edition):
    def get_title(self):
        if self['title_prefix']:
            return self['title_prefix'] + ' ' + self['title']
        else:
            return self['title']
            
    def get_title_prefix(self):
        return ''

    # let title be title_prefix + title
    title = property(get_title)
    title_prefix = property(get_title_prefix)
        
    def get_covers(self):
        covers = self.covers or query_coverstore('b', olid=self.get_olid())
        return [Image('b', c) for c in covers]
        
    def get_cover(self):
        covers = self.get_covers()
        return covers and covers[0] or None
        
    def get_cover_url(self, size):
        cover = self.get_cover()
        return cover and cover.url(size)

    def get_identifiers(self):
        """Returns (name, value) pairs of all available identifiers."""
        ids = []
        def addid(name, label, url_format=''):
            ids.append(web.storage(name=name, label=label, url_format=url_format))
        
        addid('isbn_10', 'ISBN 10')
        addid('isbn_13', 'ISBN 13')
        addid('lccn', 'LC Control Number', 'http://lccn.loc.gov/%(value)s')
        addid('oclc_numbers', 'OCLC', 'http://www.worldcat.org/oclc/%(value)s?tab=details')
        #addid('dewey_decimal_class', 'Dewey Decimal Class')
        #addid('lc_classifications', 'Library of Congress')
        
        d = MultiDict()
        d['olid'] = web.storage(name='olid', label='Open Library', value=self.key.split('/')[-1], url='', readonly=True)
        return self._prepare_identifiers(ids, d)
        
    def _prepare_identifiers(self, ids, d=None):
        d = d or MultiDict()
        
        for id in ids:
            value = self[id.name]
            if value:
                if not isinstance(value, list):
                    value = [value]
                for v in value:
                    d[id.name] = web.storage(name=id.name, label=id.label, value=v, url=id.url_format % {'value': v}, readonly=False)
                    
        return d
    
    def set_identifiers(self, identifiers):
        """Updates the edition from identifiers specified as (name, value) pairs."""
        names = ['isbn_10', 'isbn_13', 'lccn', 'oclc_numbers', 'ocaid', 'dewey_decimal_class', 'lc_classifications']
        
        d = {}
        for id in identifiers:
            name, value = id['name'], id['value']
            # ignore other identifiers for now
            if name in names:
                d.setdefault(name, []).append(value)
        
        # clear existing value first        
        for name in names:
           self._getdata().pop(name, None)
            
        for name, value in d.items():
            # ocaid is not a list
            if name == 'ocaid':
                self.ocaid = value[0]
            else:
                self[name] = value

    def get_classifications(self):
        ids = []
        def addid(name, label, url_format=''):
            ids.append(web.storage(name=name, label=label, url_format=url_format))
        
        addid('dewey_decimal_class', 'Dewey Decimal Class')
        addid('lc_classifications', 'Library of Congress')
        d = self._prepare_identifiers(ids)
        return d
                
    def get_weight(self):
        """returns weight as a storage object with value and units fields."""
        w = self.weight
        return w and UnitParser(["value"]).parse(w)
        
    def set_weight(self, w):
        self.weight = w and UnitParser(["value"]).format(w)
        
    def get_physical_dimensions(self):
        d = self.physical_dimensions
        return d and UnitParser(["height", "width", "depth"]).parse(d)
    
    def set_physical_dimensions(self, d):
        self.physical_dimensions = d and UnitParser(["height", "width", "depth"]).format(d)
        
    def get_toc_text(self):
        def row(r):
            if isinstance(r, basestring):
                # there might be some legacy docs in the system with table-of-contents
                # represented as list of strings.
                level = 0
                label = ""
                title = r
                page = ""
            else:
                level = safeint(r.get('level', '0'), 0)
                label = r.get('label', '')
                title = r.get('title', '')
                page = r.get('pagenum', '')
            return "*" * level + " " + " | ".join([label, title, page])
            
        return "\n".join(row(r) for r in self.table_of_contents)

    def set_toc_text(self, text):
        self.table_of_contents = parse_toc(text)
        
    def get_links(self):
        links1 = [web.storage(url=url, title=title) for url, title in zip(self.uris, self.uri_descriptions)] 
        links2 = list(self.links)
        return links1 + links2
        
    def get_olid(self):
        return self.key.split('/')[-1]
        
class Author(ol_code.Author):
    def get_photos(self):
        photos = self.photos or query_coverstore('a', olid=self.get_olid())
        return [Image("a", id) for id in photos]
        
    def get_photo(self):
        photos = self.get_photos()
        return photos and photos[0] or None
        
    def get_photo_url(self, size):
        photo = self.get_photo()
        return photo and photo.url(size)
    
    def get_olid(self):
        return self.key.split('/')[-1]
        
class Work(ol_code.Work):
    def get_subjects(self):
        """Return subject strings."""
        subjects = self.subjects
                
        if subjects and not isinstance(subjects[0], basestring):
            subjects = [s.name for s in subjects]
        return subjects


class Subject(client.Thing):
    def _get_solr_result(self):
        if not self._solr_result:
            name = self.name or ""
            q = {'subjects': name, "facets": True}
            self._solr_result = SearchProcessor().search(q)
        return self._solr_result
        
    def get_related_subjects(self):
        # dummy subjects
        return [web.storage(name='France', key='/subjects/places/France'), web.storage(name='Travel', key='/subjects/Travel')]
        
    def get_covers(self, offset=0, limit=20):
        editions = self.get_editions(offset, limit)
        olids = [e['key'].split('/')[-1] for e in editions]
        
        try:
            url = '%s/b/query?cmd=ids&olid=%s' % (get_coverstore_url(), ",".join(olids))
            data = urllib2.urlopen(url).read()
            cover_ids = simplejson.loads(data)
        except IOError, e:
            print >> web.debug, 'ERROR in getting cover_ids', str(e) 
            cover_ids = {}
            
        def make_cover(edition):
            edition = dict(edition)
            edition.pop('type', None)
            edition.pop('subjects', None)
            edition.pop('languages', None)
            
            olid = edition['key'].split('/')[-1]
            if olid in cover_ids:
                edition['cover_id'] = cover_ids[olid]
            
            return edition
            
        return [make_cover(e) for e in editions]
    
    def get_edition_count(self):
        d = self._get_solr_result()
        return d['matches']
        
    def get_editions(self, offset, limit=20):
        if self._solr_result and offset+limit < len(self._solr_result):
            result = self._solr_result[offset:offset+limit]
        else:
            name = self.name or ""
            result = SearchProcessor().search({"subjects": name, 'offset': offset, 'limit': limit})
        return result['docs']
        
    def get_author_count(self):
        d = self._get_solr_result()
        return len(d['facets']['authors'])
        
    def get_authors(self):
        d = self._get_solr_result()
        return [web.storage(name=a, key='/authors/OL1A', count=count) for a, count in d['facets']['authors']]
    
    def get_publishers(self):
        d = self._get_solr_result()
        return [web.storage(name=p, count=count) for p, count in d['facets']['publishers']]


class SubjectPlace(Subject):
    pass
    

class SubjectPerson(Subject):
    pass


class User(ol_code.User):
    def get_edit_history(self, limit=10, offset=0):
        return web.ctx.site.versions({"author": self.key, "limit": limit, "offset": offset})
        
    def get_email(self):
        if web.ctx.path.startswith("/admin"):
            return account.get_user_email(self.key)
            
    def get_creation_info(self):
        if web.ctx.path.startswith("/admin"):
            d = web.ctx.site.versions({'key': self.key, "sort": "-created", "limit": 1})[0]
            return web.storage({"ip": d.ip, "member_since": d.created})
            
    def get_edit_count(self):
        if web.ctx.path.startswith("/admin"):
            return web.ctx.site._request('/count_edits_by_user', data={"key": self.key})
        else:
            return 0
            
class UnitParser:
    """Parsers values like dimentions and weight.

        >>> p = UnitParser(["height", "width", "depth"])
        >>> p.parse("9 x 3 x 2 inches")
        <Storage {'units': 'inches', 'width': '3', 'depth': '2', 'height': '9'}>
        >>> p.format({"height": "9", "width": 3, "depth": 2, "units": "inches"})
        '9 x 3 x 2 inches'
    """
    def __init__(self, fields):
        self.fields = fields

    def format(self, d):
        return " x ".join(str(d[k]) for k in self.fields) + ' ' + d['units']

    def parse(self, s):
        """Parse the string and return storage object with specified fields and units."""
        pattern = "^" + " *x *".join("([0-9.]+)" for f in self.fields) + " *(.*)$"
        rx = web.re_compile(pattern)
        m = rx.match(s)
        return m and web.storage(zip(self.fields + ["units"], m.groups()))

def setup():
    client.register_thing_class('/type/edition', Edition)
    client.register_thing_class('/type/author', Author)
    client.register_thing_class('/type/work', Work)

    client.register_thing_class('/type/subject', Subject)
    client.register_thing_class('/type/place', SubjectPlace)
    client.register_thing_class('/type/person', SubjectPerson)
    client.register_thing_class('/type/user', User)