import contextlib
from typing import Callable
from typing import Generator
from typing import Iterator
from typing import List
from typing import NamedTuple

from babi._types import Protocol
from babi.margin import Margin

SetCallback = Callable[['Buf', int, str], None]
DelCallback = Callable[['Buf', int, str], None]
InsCallback = Callable[['Buf', int], None]


class Modification(Protocol):
    def __call__(self, buf: 'Buf') -> None: ...


class SetModification(NamedTuple):
    idx: int
    s: str

    def __call__(self, buf: 'Buf') -> None:
        buf[self.idx] = self.s


class InsModification(NamedTuple):
    idx: int
    s: str

    def __call__(self, buf: 'Buf') -> None:
        buf.insert(self.idx, self.s)


class DelModification(NamedTuple):
    idx: int

    def __call__(self, buf: 'Buf') -> None:
        del buf[self.idx]


class Buf:
    def __init__(self, lines: List[str]) -> None:
        self._lines = lines
        self.file_y = self.y = self._x = self._x_hint = 0

        self._set_callbacks: List[SetCallback] = []
        self._del_callbacks: List[DelCallback] = []
        self._ins_callbacks: List[InsCallback] = []

    # read only interface

    def __repr__(self) -> str:
        return (
            f'{type(self).__name__}('
            f'{self._lines!r}, x={self.x}, y={self.y}, file_y={self.file_y}'
            f')'
        )

    def __bool__(self) -> bool:
        return bool(self._lines)

    def __getitem__(self, idx: int) -> str:
        return self._lines[idx]

    def __iter__(self) -> Iterator[str]:
        yield from self._lines

    def __len__(self) -> int:
        return len(self._lines)

    # mutators

    def __setitem__(self, idx: int, val: str) -> None:
        victim = self._lines[idx]

        self._lines[idx] = val

        for set_callback in self._set_callbacks:
            set_callback(self, idx, victim)

    def __delitem__(self, idx: int) -> None:
        if idx < 0:
            idx %= len(self)
        victim = self._lines[idx]

        del self._lines[idx]

        for del_callback in self._del_callbacks:
            del_callback(self, idx, victim)

    def insert(self, idx: int, val: str) -> None:
        if idx < 0:
            idx %= len(self)

        self._lines.insert(idx, val)

        for ins_callback in self._ins_callbacks:
            ins_callback(self, idx)

    # also mutators, but implemented using above functions

    def append(self, val: str) -> None:
        self.insert(len(self), val)

    def pop(self, idx: int = -1) -> str:
        victim = self[idx]
        del self[idx]
        return victim

    def restore_eof_invariant(self) -> None:
        """the file lines will always contain a blank empty string at the end'
        to simplify rendering.  call this whenever the last line may change
        """
        if self[-1] != '':
            self.append('')

    # event handling

    def add_set_callback(self, cb: SetCallback) -> None:
        self._set_callbacks.append(cb)

    def remove_set_callback(self, cb: SetCallback) -> None:
        self._set_callbacks.remove(cb)

    def add_del_callback(self, cb: DelCallback) -> None:
        self._del_callbacks.append(cb)

    def remove_del_callback(self, cb: DelCallback) -> None:
        self._del_callbacks.remove(cb)

    def add_ins_callback(self, cb: InsCallback) -> None:
        self._ins_callbacks.append(cb)

    def remove_ins_callback(self, cb: InsCallback) -> None:
        self._ins_callbacks.remove(cb)

    @contextlib.contextmanager
    def record(self) -> Generator[List[Modification], None, None]:
        modifications: List[Modification] = []

        def set_cb(buf: 'Buf', idx: int, victim: str) -> None:
            modifications.append(SetModification(idx, victim))

        def del_cb(buf: 'Buf', idx: int, victim: str) -> None:
            modifications.append(InsModification(idx, victim))

        def ins_cb(buf: 'Buf', idx: int) -> None:
            modifications.append(DelModification(idx))

        self.add_set_callback(set_cb)
        self.add_del_callback(del_cb)
        self.add_ins_callback(ins_cb)
        try:
            yield modifications
        finally:
            self.remove_ins_callback(ins_cb)
            self.remove_del_callback(del_cb)
            self.remove_set_callback(set_cb)

    def apply(self, modifications: List[Modification]) -> List[Modification]:
        with self.record() as ret_modifications:
            for modification in reversed(modifications):
                modification(self)
        return ret_modifications

    # position properties

    @property
    def displayable_count(self) -> int:
        return len(self._lines) - self.file_y

    @property
    def x(self) -> int:
        return self._x

    @x.setter
    def x(self, x: int) -> None:
        self._x = x
        self._x_hint = x

    # movement

    def scroll_screen_if_needed(self, margin: Margin) -> None:
        # if the `y` is not on screen, make it so
        if not (self.file_y <= self.y < self.file_y + margin.body_lines):
            self.file_y = max(self.y - margin.body_lines // 2, 0)

    def _set_x_after_vertical_movement(self) -> None:
        self._x = min(len(self._lines[self.y]), self._x_hint)

    def up(self, margin: Margin) -> None:
        if self.y > 0:
            self.y -= 1
            if self.y < self.file_y:
                self.file_y = max(self.file_y - margin.scroll_amount, 0)
            self._set_x_after_vertical_movement()

    def down(self, margin: Margin) -> None:
        if self.y < len(self._lines) - 1:
            self.y += 1
            if self.y >= self.file_y + margin.body_lines:
                self.file_y += margin.scroll_amount
            self._set_x_after_vertical_movement()

    def right(self, margin: Margin) -> None:
        if self.x >= len(self._lines[self.y]):
            if self.y < len(self._lines) - 1:
                self.down(margin)
                self.x = 0
        else:
            self.x += 1

    def left(self, margin: Margin) -> None:
        if self.x == 0:
            if self.y > 0:
                self.up(margin)
                self.x = len(self._lines[self.y])
        else:
            self.x -= 1

    # screen movement

    def file_up(self, margin: Margin) -> None:
        if self.file_y > 0:
            self.file_y -= 1
            if self.y > self.file_y + margin.body_lines - 1:
                self.up(margin)

    def file_down(self, margin: Margin) -> None:
        if self.file_y < len(self._lines) - 1:
            self.file_y += 1
            if self.y < self.file_y:
                self.down(margin)
