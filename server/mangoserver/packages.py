"""Kho gói nâng cấp Client của Mango Server 1.1 (§4.1).

Thư mục `data/packages/` chứa file zip gói client. Metadata trong
`data/packages.json` (JsonStore, key "packages"):
  {version: {version, filename, sha256, size, requires_restart,
             created_at, note}}

`version` là chuỗi semver (vd "1.1.0"); so sánh bản bằng
`compare_versions(a, b)` (tách theo dấu ".", so từng số nguyên; bản
không parse được coi như 0).
"""
import os
from pathlib import Path


def compare_versions(a: str, b: str) -> int:
    """So sánh 2 chuỗi phiên bản. Trả -1 / 0 / 1 (a < b / a == b / a > b).
    Mỗi phần tách theo "." được parse thành số nguyên; phần không parse
    được coi như 0; thiếu phần coi như 0 (vd "1.1" == "1.1.0")."""
    def _parts(version):
        out = []
        for piece in str(version or "").strip().split("."):
            try:
                out.append(int(piece))
            except ValueError:
                out.append(0)
        return out or [0]

    pa, pb = _parts(a), _parts(b)
    for x, y in zip(pa, pb):
        if x != y:
            return -1 if x < y else 1
    if len(pa) != len(pb):
        rest_a = pa[len(pb):] if len(pa) > len(pb) else []
        rest_b = pb[len(pa):] if len(pb) > len(pa) else []
        if any(v != 0 for v in rest_a):
            return 1
        if any(v != 0 for v in rest_b):
            return -1
    return 0


class PackageStore:
    """Kho gói client: metadata trong JsonStore + file zip trong thư mục
    `packages_dir` (mặc định `<data_dir>/packages`)."""

    def __init__(self, store, packages_dir):
        self.store = store
        self.packages_dir = Path(packages_dir)

    def _pkgs(self):
        return self.store.data.setdefault("packages", {})

    def list(self):
        """Danh sách gói, xếp theo phiên bản tăng dần."""
        records = list(self._pkgs().values())
        records.sort(key=lambda r: [int(p) if p.isdigit() else 0
                                    for p in str(r.get("version", "")).split(".")])
        return records

    def get(self, version: str):
        if not version:
            return None
        return self._pkgs().get(str(version))

    def add(self, record: dict):
        """Thêm/cập nhật metadata 1 gói. Nếu bản cũ cùng version có tên
        file khác thì xóa file cũ. Trả bản ghi đã lưu."""
        version = str(record["version"])
        old = self._pkgs().get(version)
        if old and old.get("filename") != record.get("filename"):
            try:
                os.remove(self.packages_dir / str(old["filename"]))
            except OSError:
                pass
        self._pkgs()[version] = dict(record)
        self.store.save()
        return self._pkgs()[version]

    def delete(self, version: str) -> bool:
        """Xóa metadata + file zip của 1 gói. Trả False nếu không có gói."""
        rec = self._pkgs().pop(str(version), None)
        if rec is None:
            return False
        try:
            os.remove(self.packages_dir / str(rec.get("filename", "")))
        except OSError:
            pass
        self.store.save()
        return True

    def file_path(self, version: str):
        """Đường dẫn file zip của gói, hoặc None nếu không có gói."""
        rec = self.get(version)
        if not rec:
            return None
        return self.packages_dir / str(rec.get("filename", ""))

    def latest(self):
        """Gói có phiên bản cao nhất, hoặc None nếu kho trống."""
        records = self.list()
        return records[-1] if records else None

    def latest_newer_than(self, version: str):
        """Gói mới nhất mà phiên bản của nó lớn hơn `version`
        (dùng để báo client có bản nâng cấp). None nếu không có."""
        newer = [r for r in self.list()
                 if compare_versions(str(r.get("version", "")), version) > 0]
        return newer[-1] if newer else None
