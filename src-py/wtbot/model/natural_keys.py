from typing import ClassVar


class NaturalKeyMixin:
    natural_key_fields: ClassVar[tuple[str, ...]]

    def natural_key(self) -> tuple:
        return tuple(getattr(self, field) for field in self.natural_key_fields)

    @classmethod
    def natural_key_filter(cls, values: tuple):
        if len(values) != len(cls.natural_key_fields):
            raise ValueError("wrong natural key length")

        return [
            getattr(cls, field) == value
            for field, value in zip(cls.natural_key_fields, values)
        ]
