from mokuru.dialswitch import (VK_CONTROL, VK_LCONTROL, VK_LWIN, VK_MENU, VK_SHIFT,
                               VK_TAB, VK_VOLUME_DOWN, VK_VOLUME_MUTE, VK_VOLUME_UP,
                               Switcher)


def make():
    sent = []
    return Switcher(lambda vk, down: sent.append((vk, down))), sent


def test_dial_without_ctrl_is_volume():
    s, sent = make()
    assert s.key(VK_VOLUME_UP, True) is False
    assert sent == []


def test_ctrl_turns_walk_alt_tab_and_release_picks():
    s, sent = make()
    assert s.key(VK_LCONTROL, True) is False
    assert s.key(VK_VOLUME_UP, True) is True
    assert sent == [(VK_CONTROL, False), (VK_MENU, True), (VK_TAB, True), (VK_TAB, False)]
    assert s.key(VK_VOLUME_UP, False) is True
    sent.clear()
    s.key(VK_VOLUME_DOWN, True)
    assert sent == [(VK_SHIFT, True), (VK_TAB, True), (VK_TAB, False), (VK_SHIFT, False)]
    sent.clear()
    assert s.key(VK_LCONTROL, False) is True     # swallowed: Alt goes up instead
    assert sent == [(VK_MENU, False)]
    assert s.key(VK_VOLUME_UP, True) is False    # back to volume


def test_ctrl_press_opens_task_view():
    s, sent = make()
    s.key(VK_LCONTROL, True)
    assert s.key(VK_VOLUME_MUTE, True) is True
    assert (VK_LWIN, True) in sent and (VK_TAB, True) in sent
    assert sent[-1] == (VK_CONTROL, True)        # Ctrl still held logically
    assert s.key(VK_LCONTROL, False) is False    # plain Ctrl release passes through
