"""Read-only descriptions of encoded button behavior, without guessing IR protocols."""
from .commands import inventory, _learn, LEARN_SIZE
from .macros import get_macro
from .raw_memory import RawMemoryDocument


class ActionDescriptions:
    def __init__(self, data):
        self.data = bytes(data)
        self.commands = {(c.device_slot, c.key_id): c for c in inventory(self.data)}
        self.names = {getattr(d, 'slot', 20): d.name for d in RawMemoryDocument(self.data).devices}

    def _name(self, device, key):
        c = self.commands.get((device, key))
        if c:
            return f'{c.device_name} / {c.name}'
        return f'{self.names.get(device, f"Device {device}")} / {"Device entry" if key == 76 else f"key {key}"}'

    def _signal(self, device, key):
        pair = (device, key)
        visited = set()
        path = []
        while pair not in visited:
            visited.add(pair)
            c = self.commands.get(pair)
            if c is None:
                return ('Unresolved command', ' → '.join(path + [self._name(*pair)]) + '\nCommand target is unavailable; transmitted IR is unknown.')
            path.append(self._name(*pair))
            if c.learned == 'active':
                offset, _ = _learn(self.data, *pair)
                raw = self.data[offset:offset + LEARN_SIZE]
                prefix = (' → '.join(path[1:]) + ' · ') if len(path) > 1 else ''
                summary = prefix + 'Encoded IR ' + raw[:10].hex(' ').upper() + ' …'
                details = (' → '.join(path) + '\nLearned IR: stored 106-byte encoded record (not a decoded waveform or protocol code).\n'
                           + raw.hex(' ').upper())
                return summary, details
            target = (c.target_device, c.target_key)
            if target == pair:
                prefix = (' → '.join(path[1:]) + ' · ') if len(path) > 1 else ''
                return (prefix + 'Built-in IR unknown', ' → '.join(path) +
                        '\nBuilt-in/default assignment; IR availability and actual code have not been decoded.' +
                        ('\nAn inactive learned record is retained but is not the active assignment.' if c.learned == 'stored' else ''))
            pair = target
        return 'Shortcut cycle; IR unknown', ' → '.join(path + [self._name(*pair)]) + '\nShortcut cycle; transmitted behavior is unknown.'

    def _macro(self, device, key):
        index = 0 if key == 0 else 1 if key == 35 else key - 34 if 36 <= key <= 76 else None
        if index is None:
            return None
        macro = get_macro(self.data, device, index)
        if not macro.active:
            return None
        summary, details = [], []
        for number, step in enumerate(macro.steps, 1):
            if step.kind == 'delay':
                text = f'{"Hold" if number == 1 else "Wait"} {step.value / 10:g}s'
                detail = text + (' to trigger macro (leading delay)' if number == 1 else '')
            elif step.kind == 'device':
                text = f'Context: {self.names.get(step.value, f"Device {step.value}")}'
                detail = text + ' (macro device selection token)'
            elif step.kind == 'page':
                text = f'Page {step.value + 1}'
                detail = text + ' (page jump token)'
            else:
                text = self._name(step.device_slot, step.value)
                command = self.commands.get((step.device_slot, step.value))
                if step.device_slot == device and command is not None:
                    text = command.name.split(' · ', 1)[-1]
                signal, signal_details = self._signal(step.device_slot, step.value)
                detail = text + '\n' + signal_details
            summary.append(text)
            details.append(f'{number}. {detail}')
        mode = 'before' if macro.before else 'action'
        raw = macro.raw[:macro.used].hex(' ').upper()
        return (' → '.join(summary) or 'Empty macro',
                f'{self._name(device, key)}\nMacro sequence ({mode} mode; assignment interaction is not fully decoded).\n'
                + '\n\n'.join(details) + f'\n\nEncoded macro tokens: {raw}\n'
                'Command steps show their stored signal assignments; nested macro execution is not assumed.')

    def describe(self, device_slot, key_id):
        """Return a single-line summary and complete, plain-text details."""
        if not (type(device_slot) is int and 0 <= device_slot <= 20 and
                type(key_id) is int and 0 <= key_id <= 76):
            raise ValueError('Invalid device or button key')
        return self._macro(device_slot, key_id) or self._signal(device_slot, key_id)

    def describe_main(self, slot):
        """MAIN LCD selectors select the corresponding device and its entry macro."""
        if type(slot) is not int or not 0 <= slot < 20:
            raise ValueError('Invalid MAIN device slot')
        if slot not in self.names:
            return 'Unassigned device', f'Device slot {slot} is not configured; no command is identified.'
        label = f'Open {self.names[slot]}'
        macro = self._macro(slot, 76)
        if macro:
            return label + ' · ' + macro[0], label + '\nDevice-entry macro:\n' + macro[1]
        return label, label + '\nMAIN device selector. No device-entry macro is stored; this selector has no decoded IR action.'
