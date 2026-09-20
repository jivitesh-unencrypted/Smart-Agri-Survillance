"""
SQLite has no native timezone-aware datetime storage - a plain
SQLAlchemy DateTime column silently drops tzinfo on read, even though
every timestamp in this app is always created with
datetime.now(timezone.utc). That naive-but-actually-UTC value then
serializes to JSON without a 'Z'/offset suffix, and browsers parse an
offset-less ISO datetime string as LOCAL time (per the ECMAScript
spec) - so every timestamp silently shifts by the client's UTC offset.

UTCDateTime fixes this at the source: it always stores a naive UTC
string (stripping any tzinfo before writing, after first converting to
UTC so a stray non-UTC aware value can't corrupt storage), and always
re-attaches tzinfo=utc on the way back out. That makes every datetime
object the ORM ever returns unambiguously UTC-aware, so Pydantic/
FastAPI serialize it with an explicit offset and any client parses it
correctly - not just this frontend.
"""
from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime, dialect):
        if value is None:
            return None
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value: datetime, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value
