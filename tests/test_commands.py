import os
from pathlib import Path
import unittest
from mx700_studio.commands import inventory, copy_learned, assign_shortcut, LEARN_BASE, _update
from mx700_studio.raw_memory import section_checksum


def fixture():
    data = bytearray(b'\xff'*0x73000)
    system = bytearray(b' '*8192)
    system[2] = 10
    system[3:45] = b'\0'*42
    system[3:5] = (32).to_bytes(2,'little')
    system[5:7] = (32).to_bytes(2,'little')
    system[0x800:0x815] = b'\0'*21
    system[0x800] = system[0x801] = system[0x814] = 1
    system[0x97:0x9c] = b'MAIN '
    data[0x1000:0x3000] = system
    _update(data,0x1000,8192)
    data[2] = 9
    for dev in range(21):
        for key in range(77):
            off = 3+dev*154+key*2
            data[off:off+2] = bytes([dev,key])
        for base in (0x1f000,LEARN_BASE):
            _update(data,base+dev*8192,8192)
    data[LEARN_BASE+3+17*106:LEARN_BASE+3+18*106] = b'\x45'+bytes(range(105))
    _update(data,LEARN_BASE,8192)
    _update(data,0,4096)
    return bytes(data)

class CommandsTest(unittest.TestCase):
    def setUp(self): self.data=fixture()
    def test_inventory_rocker(self):
        item=next(c for c in inventory(self.data) if (c.device_slot,c.key_id)==(0,17))
        self.assertEqual((item.name,item.learned),('Right','active'))
    def test_shortcut_confined(self):
        edited=assign_shortcut(self.data,1,20,0,17)
        allowed={0,1,3+154+40,4+154+40}
        self.assertTrue(all(i in allowed for i,(a,b) in enumerate(zip(self.data,edited)) if a!=b))
        self.assertEqual(edited[197:199],bytes([0,17]))
        inventory(edited)
    def test_copy_confined(self):
        edited=copy_learned(self.data,1,20,0,17)
        base=LEARN_BASE+8192
        off=base+3+20*106
        allowed=set(range(off,off+106))|{base,base+1,0,1,197,198}
        self.assertTrue(all(i in allowed for i,(a,b) in enumerate(zip(self.data,edited)) if a!=b))
        self.assertEqual(edited[off:off+106],self.data[LEARN_BASE+3+17*106:LEARN_BASE+3+18*106])
        self.assertEqual(next(c for c in inventory(edited) if (c.device_slot,c.key_id)==(1,20)).learned,'active')
    def test_reject_active_target_shortcut(self):
        with self.assertRaises(ValueError): assign_shortcut(self.data,0,17,1,20)
    def test_shortcut_retains_learned_code(self):
        data=bytearray(self.data)
        offset=LEARN_BASE+3+17*106
        data[offset+105]=255
        _update(data,LEARN_BASE,8192)
        data=bytes(data)
        edited=assign_shortcut(data,0,17,1,20)
        self.assertEqual(edited[offset:offset+106], b'\xff'+data[offset:offset+105])
        # Original importer restores the padding byte after removing FF prefix.
        self.assertEqual(edited[offset+1:offset+106]+b'\xff', data[offset:offset+106])
        command=next(c for c in inventory(edited) if (c.device_slot,c.key_id)==(0,17))
        self.assertEqual(command.learned,'stored')
        self.assertEqual((command.target_device,command.target_key),(1,20))
        allowed=set(range(offset,offset+106))|{0,1,37,38,LEARN_BASE,LEARN_BASE+1}
        self.assertTrue(all(i in allowed for i,(a,b) in enumerate(zip(data,edited)) if a!=b))
    def test_malformed_source_route(self):
        for pair in ((255,255),(3,20),(0,24),(0,76)):
            data=bytearray(self.data)
            data[3+154+40:5+154+40]=bytes(pair)
            _update(data,0,4096)
            with self.assertRaises(ValueError): assign_shortcut(bytes(data),0,20,1,20)
    def test_reject_boolean_key(self):
        with self.assertRaises(ValueError): assign_shortcut(self.data,True,20,0,17)
    def test_reject_empty_copy(self):
        with self.assertRaises(ValueError): copy_learned(self.data,0,17,1,20)
    def test_reject_cycle(self):
        edited=assign_shortcut(self.data,1,20,0,20)
        with self.assertRaises(ValueError): assign_shortcut(edited,0,20,1,20)
    def test_reject_corrupt(self):
        edited=bytearray(self.data);edited[20]^=1
        with self.assertRaises(ValueError): inventory(edited)
    def test_reject_partial(self):
        with self.assertRaises(ValueError): inventory(self.data[0x1000:0x3000])
    def test_actual_backup(self):
        path=Path(os.environ.get('MX700_RAW_SAMPLE',Path(__file__).resolve().parents[2]/'sr101-original-config.bin'))
        if not path.exists(): self.skipTest('Private backup absent')
        data=path.read_bytes(); items=inventory(data)
        self.assertEqual(len(items),240)
        self.assertEqual(sum(c.learned=='active' for c in items),55)
        edited=copy_learned(data,20,20,0,20)
        self.assertNotEqual(data,edited)
        self.assertEqual(path.read_bytes(),data)
        inventory(edited)

if __name__=='__main__': unittest.main()
