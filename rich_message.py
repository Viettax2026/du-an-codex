"""Restricted rich messages and immutable Zalo UTF-16 formatting ranges."""
import json
import secrets
from bisect import bisect_left
from html import escape
from html.parser import HTMLParser

from personalization import TOKEN, personalize

COLORS = {'c_db342e', 'c_f27806', 'c_f7b503', 'c_15a85f'}
STYLES = {'b', 'i', 'u', 's', 'f_18', 'lst_1', 'lst_2', 'ind_$'} | COLORS
TAGS = {'b':'b', 'strong':'b', 'i':'i', 'em':'i', 'u':'u', 's':'s', 'strike':'s',
        'h1':'f_18', 'h2':'f_18', 'h3':'f_18', 'blockquote':'ind_$'}
BLOCKS = {'p', 'div', 'h1', 'h2', 'h3', 'blockquote', 'ul', 'ol', 'li'}
DROP = {'script', 'style', 'iframe', 'object', 'svg', 'math', 'template'}


def utf16(text):
    return len(text.encode('utf-16-le')) // 2


class MessageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text = ''
        self.ranges = []
        self.stack = []
        self.dropped = []

    def newline(self):
        if self.text and not self.text.endswith('\n'):
            self.text += '\n'

    def handle_starttag(self, tag, attrs):
        if self.dropped:
            if tag in DROP:
                self.dropped.append(tag)
            return
        if tag in DROP:
            self.dropped.append(tag)
            return
        if tag == 'br':
            self.text += '\n'
            return
        if tag in BLOCKS:
            self.newline()
        style = TAGS.get(tag)
        if tag == 'li':
            style = 'lst_2' if any(t == 'ol' for t, _, _ in self.stack) else 'lst_1'
        if tag == 'span':
            style = dict(attrs).get('data-style')
            if style not in STYLES and style != 'c_default':
                style = None
        self.stack.append((tag, len(self.text), style))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag != 'br':
            self.handle_endtag(tag)

    def close_tag(self, entry):
        tag, start, style = entry
        end = len(self.text.rstrip('\n'))
        if style and end > start:
            self.ranges.append((start, end, style))
            if tag in ('h1','h2','h3'):
                self.ranges.append((start, end, 'b'))
        if tag in BLOCKS:
            self.newline()

    def handle_endtag(self, tag):
        if self.dropped:
            if tag == self.dropped[-1]:
                self.dropped.pop()
            return
        match = next((i for i in range(len(self.stack)-1, -1, -1) if self.stack[i][0] == tag), None)
        if match is not None:
            while len(self.stack) > match:
                self.close_tag(self.stack.pop())

    def handle_data(self, data):
        if not self.dropped:
            self.text += data

    def result(self):
        while self.stack:
            self.close_tag(self.stack.pop())
        left = len(self.text) - len(self.text.lstrip())
        text = self.text.strip()
        ranges = sorted({(max(0,a-left), min(len(text),b-left), st) for a,b,st in self.ranges
                         if min(len(text),b-left) > max(0,a-left)})
        # Inner colors override outer ones. The editor's default-color marker
        # removes inherited color without emitting an unsupported SDK style.
        colors = [(max(0,a-left),min(len(text),b-left),st) for a,b,st in self.ranges
                  if st in COLORS or st == 'c_default']
        if len(colors) > 400:
            raise ValueError('Nội dung có quá nhiều vùng màu. Vui lòng đơn giản hóa định dạng.')
        ranges = [item for item in ranges if item[2] not in COLORS and item[2] != 'c_default']
        points = sorted({0,len(text),*(a for a,_,_ in colors),*(b for _,b,_ in colors)})
        colored = []
        for a,b in zip(points,points[1:]):
            if b <= a:continue
            style = next((st for start,end,st in colors if start <= a and end >= b),None)
            if style in COLORS:
                if colored and colored[-1][1] == a and colored[-1][2] == style:
                    colored[-1] = (colored[-1][0],b,style)
                else:colored.append((a,b,style))
        ranges = sorted(ranges + colored)
        if len(ranges) > 400:
            raise ValueError('Nội dung có quá nhiều vùng định dạng. Vui lòng đơn giản hóa định dạng.')
        return text, ranges


def parse_html(value):
    if len(value) > 200000:
        raise ValueError('Nội dung định dạng quá dài.')
    parser = MessageParser()
    parser.feed(value)
    parser.close()
    return parser.result()


def markup(text, ranges):
    """Escape every character; only emit our own tags and attributes."""
    boundaries = sorted({0,len(text),*(a for a,_,_ in ranges),*(b for _,b,_ in ranges)})
    result, opened = [], []
    def opening(st):
        tag = {'b':'strong','i':'em','u':'u','s':'s'}.get(st)
        return f'<{tag}>' if tag else f'<span data-style="{st}">'
    def closing(st):
        tag = {'b':'strong','i':'em','u':'u','s':'s'}.get(st, 'span')
        return f'</{tag}>'
    for a,b in zip(boundaries, boundaries[1:]):
        tags = sorted({st for start,end,st in ranges if start <= a and end >= b}, key=lambda st:(st in {'b','i','u','s'},st))
        common = 0
        while common < min(len(opened),len(tags)) and opened[common] == tags[common]:
            common += 1
        result.extend(closing(st) for st in reversed(opened[common:]))
        result.extend(opening(st) for st in tags[common:])
        result.append(escape(text[a:b]).replace('\n','<br>'))
        opened = tags
    result.extend(closing(st) for st in reversed(opened))
    return ''.join(result)



def variant_spans(text):
    """Split only outer pipes, before interpreting spins or personalization."""
    spans, start, depth, i = [], 0, 0, 0
    while i < len(text):
        char = text[i]
        if char == '\\' and i+1 < len(text) and text[i+1] in '\\|{}':
            i += 2
            continue
        if char == '{':
            depth += 1
        elif char == '}':
            depth = max(0,depth-1)
        elif char == '|' and depth == 0:
            spans.append((start,i))
            start = i+1
        i += 1
    spans.append((start,len(text)))
    if len(spans) > 20 or utf16(text) > 40000:
        raise ValueError('Tối đa 20 biến thể, mỗi biến thể tối đa 2.000 ký tự.')
    trimmed = []
    for a,b in spans:
        while a < b and text[a].isspace():
            a += 1
        while b > a and text[b-1].isspace():
            b -= 1
        if a == b and len(spans) > 1:
            raise ValueError('Biến thể đang trống. Nhập nội dung ở hai bên dấu |.')
        trimmed.append((a,b))
    return trimmed


def spin_nodes(text, a, b):
    """Parse bounded choices while retaining original character positions.

    Personalization tokens are atomic, so their braces and any pipes inside
    them never become random choices. Inserted customer data is handled later.
    """
    count = 0

    def length(nodes):
        return sum(utf16(text[node]) if isinstance(node,int) else max(node[1]) for node in nodes)

    def sequence(i, depth=0):
        nonlocal count
        options = [[]]
        while i < b:
            char = text[i]
            if char == '\\' and i+1 < b and text[i+1] in '\\|{}':
                options[-1].append(i+1)
                i += 2
                continue
            token = TOKEN.match(text,i,b)
            if token:
                options[-1].extend(range(i,token.end()))
                i = token.end()
                continue
            if text.startswith('#{',i):
                # Preserve malformed/unknown personalization for the existing
                # validator; never turn it into a different valid expression.
                end, balance = i+2, 1
                while end < b and balance:
                    balance += (text[end]=='{') - (text[end]=='}')
                    end += 1
                options[-1].extend(range(i,end))
                i = end
                continue
            if char == '{':
                if depth >= 10:
                    raise ValueError('Cú pháp biến thể lồng nhau tối đa 10 cấp.')
                start = i
                children, i = sequence(i+1,depth+1)
                if len(children) > 1:
                    count += 1
                    if count > 100:
                        raise ValueError('Tối đa 100 nhóm lựa chọn {a|b|c} trong một biến thể.')
                    options[-1].append((children,[length(child) for child in children]))
                else:
                    options[-1].extend([start,*children[0],i-1])
                continue
            if char == '}' and depth:
                return options,i+1
            if char == '|' and depth:
                options.append([])
                if len(options) > 20:
                    raise ValueError('Mỗi nhóm {a|b|c} có tối đa 20 lựa chọn.')
            else:
                options[-1].append(i)
            i += 1
        if depth:
            raise ValueError('Thiếu dấu } đóng nhóm lựa chọn. Dùng \\{ nếu muốn giữ dấu ngoặc trong tin nhắn.')
        return options,i

    return sequence(a)[0][0]


def select_variant(text, ranges, index=0, *, max_length=False):
    spans = variant_spans(text)
    a,b = spans[index % len(spans)]
    positions = []
    def select(nodes):
        for node in nodes:
            if isinstance(node,int):
                positions.append(node)
            else:
                options,lengths = node
                select(options[lengths.index(max(lengths))] if max_length else secrets.choice(options))
    select(spin_nodes(text,a,b))
    clipped = []
    for start,end,style in ranges:
        start,end = bisect_left(positions,start),bisect_left(positions,end)
        if end > start:
            clipped.append((start,end,style))
    return ''.join(text[i] for i in positions), clipped


def read_message(form):
    html = form.get('message_html','') if form.get('rich_message') == 'yes' else ''
    if html:
        text, ranges = parse_html(html)
        html = markup(text, ranges)
        parse_html(html)  # Canonical output must remain within the same complexity limits.
    else:
        text = form.get('message','').strip()
    for index in range(len(variant_spans(text))):
        variant, _ = select_variant(text, [], index, max_length=True)
        if text and not variant.strip():
            raise ValueError(f'Biến thể {index+1} không có nội dung.')
        if utf16(variant) > 2000:
            raise ValueError(f'Biến thể {index+1} vượt 2000 ký tự. Emoji được tính theo giới hạn của Zalo.')
    personalize(text, {}, strict=False)
    return text, html


def render_message(message, html, contact, zalo=None, strict=True, variant_index=0):
    if html:
        source, ranges = parse_html(html)
        if source != message:
            raise ValueError('Nội dung và định dạng không khớp. Vui lòng lưu lại nội dung.')
    else:
        source, ranges = message, []
    source, ranges = select_variant(source, ranges, variant_index)
    # Personalize before converting offsets to Zalo's UTF-16 units. A token may span tags.
    replacements = [(m.start(),m.end(),personalize(m.group(),contact,zalo,strict=strict)) for m in TOKEN.finditer(source)]
    def offset(pos, end=False):
        shift = 0
        for a,b,value in replacements:
            if pos <= a:
                break
            if pos < b:
                return a + shift + (len(value) if end else 0)
            shift += len(value)-(b-a)
        return pos+shift
    text = personalize(source,contact,zalo,strict=strict)
    if message and not text.strip():
        raise ValueError('Nội dung sau khi chọn biến thể đang trống. Bổ sung nội dung ngoài nhóm lựa chọn.')
    if utf16(text) > 2000:
        raise ValueError('Tin nhắn sau cá nhân hóa vượt 2000 ký tự.')
    styles=[]
    for a,b,st in ranges:
        a,b=offset(a),offset(b,True)
        if b>a:
            item={'start':utf16(text[:a]),'len':utf16(text[a:b]),'st':st}
            if st=='ind_$':
                item['indentSize']=1
            if item not in styles:
                styles.append(item)
    return text,styles


def load_styles(value, text):
    try:
        styles=json.loads(value or '[]')
        positions={utf16(text[:i]):i for i in range(len(text)+1)}
        if not isinstance(styles,list) or len(styles)>400:
            raise ValueError()
        for s in styles:
            if not isinstance(s,dict) or set(s)-{'start','len','st','indentSize'} or s.get('st') not in STYLES:
                raise ValueError()
            if type(s.get('start')) is not int or type(s.get('len')) is not int or s['len']<=0 or s['start'] not in positions or s['start']+s['len'] not in positions:
                raise ValueError()
            if 'indentSize' in s and (s['st']!='ind_$' or type(s['indentSize']) is not int or not 1<=s['indentSize']<=5):
                raise ValueError()
        return styles
    except (ValueError,TypeError,KeyError) as error:
        raise ValueError('Định dạng bản xem trước không hợp lệ. Không gửi tin.') from error


def display_message(text, styles='[]'):
    from markupsafe import Markup
    try:
        spans=load_styles(styles,text)
        positions={utf16(text[:i]):i for i in range(len(text)+1)}
        return Markup(markup(text,[(positions[s['start']],positions[s['start']+s['len']],s['st']) for s in spans]))
    except ValueError:
        return text
