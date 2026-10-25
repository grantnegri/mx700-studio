import unittest
from pathlib import Path
from mx700_studio.macros import (BACKUP_SIZE, MACRO_FILE_OFFSET, BANK_SIZE, RECORD_SIZE,
    get_macro, parse_macros, set_delay, insert_delay, remove_delay, validate_delay_changes)


def fixture(record=b'\x28\xc5\x28\xc5\x28', slot=0, index=5):
    data = bytearray(BACKUP_SIZE)
    for dev in range(21):
        base = MACRO_FILE_OFFSET + dev * BANK_SIZE
        bank = bytearray(b'\xff' * BANK_SIZE)
        bank[2] = 0x28 + dev * 2
        if dev == slot:
            start = 3 + index * RECORD_SIZE
            bank[start:start + RECORD_SIZE] = record.ljust(RECORD_SIZE, b'\xff')
        bank[:2] = ((0x852 + sum(bank[2:])) & 0xffff).to_bytes(2, 'big')
        data[base:base + BANK_SIZE] = bank
    return bytes(data)


class MacroTests(unittest.TestCase):
    def test_decode_commands_delays_and_trigger(self):
        m = parse_macros(fixture())[0]
        self.assertEqual((m.device_slot, m.index, m.key_id, m.before), (0, 5, 39, False))
        self.assertEqual([(s.kind,s.value) for s in m.steps],
                         [('command',40),('delay',5),('command',40),('delay',5),('command',40)])

    def test_before_macro_and_context(self):
        m = get_macro(fixture(b'\xff\x83\x14\xa2\xc1'),0,5)
        self.assertTrue(m.before)
        self.assertEqual([(s.kind,s.value,s.device_slot) for s in m.steps],
                         [('device',3,3),('command',20,3),('page',2,3),('delay',1,3)])

    def test_replace_preserves_other_bytes(self):
        original = fixture()
        changed = set_delay(original,0,5,1,10)
        self.assertEqual(get_macro(changed,0,5).steps[1].tenths,10)
        differences = {i for i,(a,b) in enumerate(zip(original,changed)) if a!=b}
        self.assertLessEqual(differences,{MACRO_FILE_OFFSET,MACRO_FILE_OFFSET+1,
                                       MACRO_FILE_OFFSET+3+5*190+1})
        self.assertEqual(get_macro(original,0,5).steps[1].tenths,5)

    def test_delay_split_and_merge(self):
        for value in (1,60,61,62,122,300):
            changed = set_delay(fixture(),0,5,1,value)
            self.assertEqual(get_macro(changed,0,5).steps[1].value,value)
            self.assertEqual(set_delay(changed,0,5,1,5),fixture())

    def test_insertion_and_removal(self):
        original = fixture()
        changed = insert_delay(original,0,5,2,15)
        self.assertEqual([s.value for s in get_macro(changed,0,5).steps], [40,5,15,40,5,40])
        self.assertEqual(remove_delay(changed,0,5,2),original)
        changed = insert_delay(original,0,5,5,20)
        self.assertEqual(get_macro(changed,0,5).steps[-1].value,20)

    def test_empty_is_not_created(self):
        with self.assertRaisesRegex(ValueError,'Create new'):
            insert_delay(fixture(),0,4,0,10)

    def test_reject_invalid_inputs(self):
        original=fixture()
        for value in (0,-1,301,1.5,True):
            with self.assertRaises(ValueError):set_delay(original,0,5,1,value)
        with self.assertRaises(ValueError):set_delay(original,0,5,0,10)
        for idx in (-1,43):
            with self.assertRaises(ValueError):get_macro(original,0,idx)
        with self.assertRaises(ValueError):get_macro(original[:8192],0,5)
        broken=bytearray(original);broken[MACRO_FILE_OFFSET+2]=0
        with self.assertRaises(ValueError):get_macro(broken,0,5)
        broken=bytearray(original);broken[MACRO_FILE_OFFSET]=0
        with self.assertRaises(ValueError):get_macro(broken,0,5)

    def test_reject_opaque_tail_and_overflow(self):
        with self.assertRaisesRegex(ValueError,'opaque'):
            set_delay(fixture(b'\x28\xc5\xff\x01'),0,5,1,10)
        with self.assertRaisesRegex(ValueError,'capacity'):
            insert_delay(fixture(b'\x28'*189),0,5,0,10)
        with self.assertRaisesRegex(ValueError,'terminator'):
            get_macro(fixture(b'\x28'*190),0,5)

    def test_independent_validator(self):
        original=fixture()
        changed=set_delay(original,0,5,1,15)
        self.assertEqual(validate_delay_changes(original,changed),(0,))
        self.assertEqual(validate_delay_changes(original,original),())
        with self.assertRaisesRegex(ValueError,'command'):
            validate_delay_changes(original,fixture(b'\x29\xc5\x28\xc5\x28'))
        with self.assertRaisesRegex(ValueError,'outside'):
            validate_delay_changes(original,b'\x01'+changed[1:])
        with self.assertRaisesRegex(ValueError,'assignment'):
            validate_delay_changes(original,fixture(b'\xff\x28\xc5\x28'))

    def test_real_backup(self):
        path=Path(__file__).resolve().parents[2]/'sr101-original-config.bin'
        if not path.exists():self.skipTest('Private hardware backup not bundled')
        original=path.read_bytes()
        macros=parse_macros(original)
        self.assertEqual([(m.device_slot,m.index) for m in macros],[(0,5),(0,20)])
        self.assertEqual([s.value for s in macros[0].steps],[40,5,40,5,40])
        for macro in macros:
            changed=set_delay(original,macro.device_slot,macro.index,1,10)
            self.assertEqual(set_delay(changed,macro.device_slot,macro.index,1,5),original)


if __name__=='__main__': unittest.main()
