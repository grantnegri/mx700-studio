"""Button routing and opaque learned-code copying recovered from MXM07M.

No IR synthesis or guessed code decoding. All edits return a separate full backup.
"""
from dataclasses import dataclass
from .raw_memory import RawMemoryDocument, section_checksum

FULL_SIZE = 0x73000
LEARN_BASE = 0x49000  # remote 0x52000 minus backup base 0x9000
BANK_SIZE = 0x2000
LEARN_SIZE = 106
HARD_NAMES = ('Power On','Channel +','Channel −','Volume +','Volume −','Mute',
              '1','2','3','4','5','6','7','8','9','0','Previous channel',
              'Right','Left','Select','Up','Down','Enter','+10','Reserved','Reserved',
              'Play','Rewind','Fast forward','Stop','Pause','Guide','Menu','Info','Exit','Power Off')

@dataclass(frozen=True)
class Command:
    device_slot: int
    key_id: int
    device_name: str
    name: str
    target_device: int
    target_key: int
    learned: str
    macro: bool
    offset: int
    @property
    def status(self):
        if self.macro: return 'Macro'
        if self.learned == 'active': return 'Learned IR'
        if (self.target_device, self.target_key) != (self.device_slot, self.key_id):
            return f'Shortcut → device {self.target_device}, key {self.target_key}'
        return 'Built-in/default (IR availability unverified)'


def _validate(data):
    if len(data) != FULL_SIZE:
        raise ValueError('Button editing requires a complete 471040-byte remote backup')
    RawMemoryDocument(data)
    _check_section(data, 0, 4096)


def _check_section(data, start, size):
    section = data[start:start+size]
    if len(section) != size or int.from_bytes(section[:2], 'big') != section_checksum(section):
        raise ValueError(f'Configuration checksum mismatch at file offset 0x{start:x}')


def _update(data, start, size):
    data[start:start+2] = section_checksum(data[start:start+size]).to_bytes(2, 'big')


def _location(device, key):
    if type(device) is not int or type(key) is not int or not 0 <= device <= 20 or not 0 <= key <= 76:
        raise ValueError('Invalid device or button key')
    return 3 + device*154 + key*2


def _macro(data, device, key):
    index = 0 if key == 0 else 1 if key == 35 else key-34 if 36 <= key <= 76 else None
    if index is None: return False
    start = 0x1f000 + device*BANK_SIZE
    _check_section(data, start, BANK_SIZE)
    offset = start + 3 + index*190
    return data[offset:offset+2] != b'\xff\xff'


def _learn(data, device, key):
    start = LEARN_BASE + device*BANK_SIZE
    _check_section(data, start, BANK_SIZE)
    offset = start + 3 + key*LEARN_SIZE
    raw = data[offset:offset+LEARN_SIZE]
    state = 'none' if raw[:2] == b'\xff\xff' else 'stored' if raw[0] == 255 else 'active'
    return offset, state


def inventory(data):
    """List existing device hard/LCD buttons; MAIN LCD selectors are not commands."""
    _validate(data)
    doc = RawMemoryDocument(data)
    result = []
    for device in doc.devices:
        slot = getattr(device, 'slot', 20)
        keys = list(k for k in range(36) if k not in (24,25))
        labels = {}
        if slot != 20:
            for page_index,page in enumerate(device.pages):
                for button in page.buttons:
                    key = 36 + page_index*10 + button.record_id - 0x801
                    keys.append(key)
                    labels[key] = f'Page {page_index+1} · {button.label or "(blank)"}'
        for key in keys:
            offset = _location(slot,key)
            _,state = _learn(data,slot,key)
            result.append(Command(slot,key,device.name, HARD_NAMES[key] if key<36 else labels[key],
                                  data[offset],data[offset+1],state,_macro(data,slot,key),offset))
    return result


def _existing(data, device, key):
    _location(device, key)
    matches = [c for c in inventory(data) if (c.device_slot,c.key_id)==(device,key)]
    if not matches: raise ValueError('Choose an existing device button')
    return matches[0]


def assign_shortcut(data, target_device, target_key, source_device, source_key):
    """Point a button at another command, retaining a learned code as inactive."""
    _validate(data)
    target = _existing(data,target_device,target_key)
    source = _existing(data,source_device,source_key)
    if target.macro:
        raise ValueError('Target has a macro; edit it in the macro editor first')
    target_learn_offset, _ = _learn(data, target_device, target_key)
    if target.learned == 'active' and data[target_learn_offset+LEARN_SIZE-1] != 255:
        raise ValueError('Target learned code fills its record; cannot retain it as inactive without truncation')
    if source.macro:
        raise ValueError('Macro sources are not supported by command shortcuts')
    target_pair = (target_device,target_key)
    pair = (source_device,source_key)
    visited = {target_pair}
    available = {(c.device_slot, c.key_id) for c in inventory(data)}
    while True:
        if pair in visited: raise ValueError('Shortcut would create a cycle')
        if pair not in available: raise ValueError('Shortcut chain references an unavailable device or button')
        visited.add(pair)
        offset = _location(*pair)
        if _macro(data, *pair):
            raise ValueError('Shortcut chain leads to a macro')
        next_pair = tuple(data[offset:offset+2])
        _,state = _learn(data,*pair)
        if state == 'active' or next_pair == pair: break
        pair = next_pair
    result = bytearray(data)
    offset = target.offset
    result[offset:offset+2] = bytes(pair)
    if target.learned == 'active':
        # RVA1b5a0 prefixes FF for inactive learned data. Only discard a trailing
        # FF, which the reverse conversion RVA1b640 restores automatically.
        result[target_learn_offset:target_learn_offset+LEARN_SIZE] = (
            b'\xff' + data[target_learn_offset:target_learn_offset+LEARN_SIZE-1])
        _update(result,LEARN_BASE+target_device*BANK_SIZE,BANK_SIZE)
    _update(result,0,4096)
    return bytes(result)


def copy_learned(data, target_device, target_key, source_device, source_key):
    """Copy a known active learned IR record; preserve every unrelated byte."""
    _validate(data)
    target = _existing(data,target_device,target_key)
    source = _existing(data,source_device,source_key)
    if target.macro: raise ValueError('Target has a macro; remove or edit it in the macro editor first')
    if source.macro or source.learned != 'active':
        raise ValueError('Choose a source with active learned IR and no macro')
    source_offset,_ = _learn(data,source_device,source_key)
    target_offset,_ = _learn(data,target_device,target_key)
    result = bytearray(data)
    result[target_offset:target_offset+LEARN_SIZE] = data[source_offset:source_offset+LEARN_SIZE]
    result[target.offset:target.offset+2] = bytes((target_device,target_key))
    _update(result,LEARN_BASE+target_device*BANK_SIZE,BANK_SIZE)
    _update(result,0,4096)
    return bytes(result)
