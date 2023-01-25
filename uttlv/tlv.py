from __future__ import annotations
from typing import Dict, Any
from .encoder import *
from binascii import hexlify
import enum
import math


class TLV:
    '''
    Class that represents a TLV (tag-length-value) object.

    More: https://en.wikipedia.org/wiki/Type-length-value

    If you want to parse the values to real type instead of seeing
    as byte array, set the tag_map attribute with a dict:
        {
            <tag value>: <class name>,
            <tag value>: <class name>,
            ...
        }

        where:
            tag value is the int tag value.
            class name is the name of the class that represents the type 
                of the value.
    '''
    Config = enum.Enum('Config', 'Type Name Tmpl')
    _global_tag_map = {}

    def __init__(self, indent=4, tag_size=1, len_size=None, endian='big', tv=False):
        '''
        :args:
            indent: How many spaces to use in tree() method
            tag_size: How many bytes a tag will contain in the array
            len_size: How many bytes the length info will occupy in the final
                        array, None (default) for automatically determine per
                        field
        '''
        super().__init__()
        self.indent = indent
        self.tag_size = tag_size
        self.len_size = len_size
        self.endian = endian
        self.tv = tv
        self._items = {}
        self._local_tag_map = None

    @property
    def tag_map(self) -> Dict:
        if self._local_tag_map is not None:
            return self._local_tag_map
        else:
            return TLV._global_tag_map

    def __setitem__(self, key, value):
        real_key = self.__getkey__(key)
        self.check_key(real_key)
        self.check_value(value)
        self._items[real_key] = value
        return None

    def __getitem__(self, key):
        real_key = self.__getkey__(key)
        return self._items[real_key]

    def __getkey__(self, key):
        '''Get real tag from a given string'''
        if isinstance(key, int):
            return key
        if isinstance(key, str):
            for k, v in self.tag_map.items():
                name = v.get(TLV.Config.Name)
                if name and name == key:
                    return k
            raise AttributeError(f'Key {key} not found')
        # Invalid key type
        raise KeyError(f'Invalid key {str(key)}')

    def __getattr__(self, name):
        return self.__getitem__(name)

    def __eq__(self, other):
        b = self.to_byte_array()
        a = other.to_byte_array()
        return a == b

    def __hash__(self):
        return hash(self.to_byte_array())

    def __iter__(self):
        return TLVIterator(self)

    def _new_equivalent_tlv(self) -> TLV:
        '''Creates a new TLV object with the same decode settings as self. Useful for parsing nested structures.'''
        return TLV(self.indent, self.tag_size, self.len_size, self.endian, self.tv)

    @classmethod
    def set_tag_map(cls, map: Dict) -> None:
        '''Set a tag map globally for all classes (DEPRECATED, please use set_global_tag_map)

        :args:
            map: dict with keys names
        '''
        cls.set_global_tag_map(map)

    @classmethod
    def set_global_tag_map(cls, map: Dict) -> None:
        '''Set a tag map globally for all classes

        :args:
            map: dict with keys names
        '''
        # Check if the map has correct types
        al_types = ALLOWED_TYPES.keys()
        for k, v in map.items():
            if not isinstance(v, dict):
                raise TypeError('Invalid tag config type')
            t = v.get(TLV.Config.Type, '')
            if t not in al_types:
                raise AttributeError(f'Invalid tag type {t} for {k} -> {v}')
        cls._global_tag_map = map

    def set_local_tag_map(self, map: Dict) -> None:
        '''Set a class-instance-specific tag map.

        :args:
            map: tag map to set class instance to.
        '''
        self._local_tag_map = map

        # Iterate through any nested tag maps
        for index, cfg in map.items():
            tg_type = cfg.get(TLV.Config.Type)
            if tg_type is not None and type(tg_type) is dict:
                if index not in self._items:
                    self._items[index] = self._new_equivalent_tlv()
                self._items[index].set_local_tag_map(tg_type)

    def check_key(self, key: int) -> bool:
        '''Check if key is valid is inside limits.
        
        :args:
            key: key int value.
        '''
        if not isinstance(key, int) and (key <= 0 or key >= 2**16):
            raise TypeError('Invalid key format.')
        return True

    def check_value(self, value: Any[TLV, str, int, bytes]) -> bool:
        '''Check if value class is a valid one.
        
        :args:
            value: value to be inserted.
        '''
        if not any(isinstance(value, t) for t in ALLOWED_TYPES):
            raise TypeError(f'Invalid value type format {type(value)}.')
        return True

    def encode_length(self, value: bytes) -> bytes:
        '''Translate the length of value into an array.'''
        required_len_size = math.ceil(len(value).bit_length() / 8)
        if required_len_size > 16:
            raise AttributeError(f'Max allowed value length is {2**(8*15)-1} bytes, given value is {len(value)} bytes')

        if not self.len_size:
            if len(value) < 128:
                return len(value).to_bytes(1, byteorder=self.endian)

            return (
                bytes((0x80 + required_len_size,)) +
                len(value).to_bytes(required_len_size, byteorder=self.endian)
            )

        if self.len_size < required_len_size:
            raise ValueError(f'{value} takes up {required_len_size} bytes, but len_size was defined as {self.len_size}')

        return len(value).to_bytes(self.len_size, byteorder=self.endian)

    def to_byte_array(self) -> bytes:
        '''Translate all keys and values into an array of bytes.'''
        values = bytes()
        for k, v in self._items.items():
            frm = ALLOWED_TYPES.get(type(v))
            value = frm().default(v)
            # Create array
            values += int(k).to_bytes(self.tag_size, byteorder=self.endian)
            values += self.encode_length(value)
            values += value
        return values

    def tree(self, offset: int = 0, use_names: bool = False) -> str:
        '''Print a tree view of the object.'''
        s = '' if offset == 0 else '\r\n'
        for k, v in self._items.items():
            frm = ALLOWED_TYPES.get(type(v))
            value = frm().to_string(v, offset, use_names)
            # Create line
            tag = str(hexlify(int(k).to_bytes(self.tag_size, byteorder=self.endian)), 'ascii')
            if use_names:
                map = self.tag_map.get(k, None)
                if map:
                    name = map.get(TLV.Config.Name, None) 
                    if name:
                        tag = name
            s += f'{" " * offset}{tag}: {value}\r\n'
        return s

    def decode_len_size(self, data: bytes) -> int:
        if data[0] < 0x80:
            return 1
        return data[0] - 0x80 + 1

    def parse_array(self, data: Any[list, bytes]) -> bool:
        '''Parse a byte array into a TLV object'''
        if isinstance(data, list):
            data = bytes(data)
        elif not isinstance(data, bytes):
            raise TypeError('Data must be bytes type.')
        # Check size
        min_len_size = self.len_size or 1
        min_size = min_len_size + self.tag_size
        if len(data) < min_size:
            raise AttributeError(f'Data must be at least {min_size} bytes long')
        # Start parsing
        aux = data
        while len(aux) > min_size:
            # Tag value
            t = int.from_bytes(aux[:self.tag_size], byteorder=self.endian)
            # Strip tag value, length (if any) and value remain
            aux = aux[self.tag_size:]
            tg_cfg = self.tag_map.get(t)
            len_size = 0
            l = 0
            tmpl = None
            if self.tv:
                if tg_cfg is not None:
                    tmpl = tg_cfg.get(TLV.Config.Tmpl)
                    if tmpl is not None:
                        l = struct.calcsize(tmpl)
                    else:
                        raise AttributeError(f'Missing template to decode attribute {hexlify(t)}')
                else:
                    raise AttributeError(f'Unknown attribute {t} in TV decoding')
            else:
                # Len value
                len_size = self.len_size or self.decode_len_size(aux)
                offset = 0 if len_size == 1 else 1
                l = int.from_bytes(aux[offset:len_size], byteorder=self.endian)
            # Value
            aux = aux[len_size:]
            v = aux[:l]
            # Check if tag has any parser
            if tg_cfg is not None:
                tg_type = tg_cfg.get(TLV.Config.Type)
                if tg_type is not None:
                    # *Ideally* we would include this in ALLOWED_TYPES, but this is the easiest way I can think of
                    # to pass in the tag map config at the same time.
                    if type(tg_type) is dict:
                        v = NestedEncoder(tg_type).parse(v, self._new_equivalent_tlv())
                    else:
                        frm = ALLOWED_TYPES.get(tg_type)
                        if frm is not None:
                            v = frm(tmpl = tg_cfg.get(TLV.Config.Tmpl)).parse(v, self._new_equivalent_tlv())
            # Set value
            self.__setitem__(t, v)
            # Next value
            aux = aux[l:]
        # Done parsing
        return True


class EmptyTLV(TLV):
    '''Empty TLV'''
    def __init__(self, tag: int, **kwargs):
        super().__init__(**kwargs)
        self.tag = tag

    def __setitem__(self, key, value):
        raise TypeError('Invalid argument')

    def to_byte_array(self) -> bytes:
        value = int(self.tag).to_bytes(self.tag_size, byteorder='big')
        len_size = self.len_size or 1
        value += int(0).to_bytes(len_size, byteorder='big')
        return value

    def tree(self, offset: int = 0, use_names: bool = False) -> str:
        s = '' if offset == 0 else '\r\n'
        tag = str(hexlify(int(self.tag).to_bytes(self.tag_size, byteorder='big')), 'ascii')
        if use_names:
            map = TLV.tag_map.get(self.tag, None)
            if map:
                name = map.get('name', None)
                tag = tag if not name else name
        s += f'{" " * offset}{tag}\r\n'
        return s


class TLVIterator:
    '''Iterator class'''
    def __init__(self, tlv: TLV):
        self._tlv = tlv
        self._it = iter(self._tlv._items)

    def __next__(self):
        ''''Returns the next value from items dictionary '''
        return next(self._it)



ALLOWED_TYPES = {
    TLV: DefaultEncoder,
    int: IntEncoder,
    struct: StructEncoder,
    bytes: BytesEncoder,
    str: Utf8Encoder,
}
