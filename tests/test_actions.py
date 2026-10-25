import unittest
from test_commands import fixture
from mx700_studio.actions import ActionDescriptions
from mx700_studio.commands import _update, assign_shortcut


def sample():
    data = bytearray(fixture())
    for slot in range(21):
        base = 0x1f000 + slot * 8192
        data[base + 2] = 0x28 + 2 * slot
        _update(data, base, 8192)
    return bytes(data)


class ActionDescriptionsTests(unittest.TestCase):
    def test_exact_learned_record(self):
        data = sample()
        summary, details = ActionDescriptions(data).describe(0, 17)
        self.assertIn('IR 45 00 01', summary)
        self.assertIn('not a decoded waveform', details)
        raw = data[0x49000+3+17*106:0x49000+3+18*106]
        self.assertIn(raw.hex(' ').upper(), details)
        self.assertEqual(data, sample())

    def test_resolved_shortcut(self):
        data = assign_shortcut(sample(), 1, 20, 0, 17)
        summary, details = ActionDescriptions(data).describe(1, 20)
        self.assertIn('Right', summary)
        self.assertIn('IR 45 00', summary)
        self.assertIn('Up', details)

    def test_unknown_builtin(self):
        summary, details = ActionDescriptions(sample()).describe(0, 20)
        self.assertIn('unknown', summary)
        self.assertIn('availability', details)

    def test_macro_and_main_entry(self):
        data = bytearray(sample())
        base = 0x1f000
        offset = base + 3 + 42 * 190
        data[offset:offset+6] = bytes([17, 0xc5, 17, 0x81, 20, 255])
        _update(data, base, 8192)
        summary, details = ActionDescriptions(data).describe_main(0)
        self.assertIn('Right → Wait 0.5s', summary)
        self.assertIn('Context:', summary)
        self.assertIn('106-byte', details)
        self.assertIn('nested macro', details)

    def test_leading_delay_is_hold(self):
        data = bytearray(sample())
        data[0x1f003:0x1f006] = bytes([0xc5, 17, 255])
        _update(data, 0x1f000, 8192)
        summary, details = ActionDescriptions(data).describe(0, 0)
        self.assertTrue(summary.startswith('Hold 0.5s'))
        self.assertIn('to trigger', details)

    def test_main_selection_and_unassigned(self):
        desc = ActionDescriptions(sample())
        self.assertTrue(desc.describe_main(0)[0].startswith('Open '))
        self.assertEqual(desc.describe_main(19)[0], 'Unassigned device')

    def test_cycle_and_missing(self):
        data = bytearray(sample())
        data[3+20*2:5+20*2] = bytes([1, 20])
        data[3+154+20*2:5+154+20*2] = bytes([0, 20])
        _update(data, 0, 4096)
        self.assertIn('cycle', ActionDescriptions(data).describe(0, 20)[0])
        self.assertIn('Unresolved', ActionDescriptions(data).describe(19, 20)[0])
