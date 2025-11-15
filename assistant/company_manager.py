from typing import Dict, List, Optional
import time


class CompanyManager:
    def __init__(self):
        self.companies: Dict[str, Dict[str, object]] = {}
        self.unit_to_company: Dict[int, str] = {}
        self._seq = 0
        self._code_seq = 0
        self._code_to_name: Dict[str, str] = {}
        self._name_to_code: Dict[str, str] = {}
        self._brigade_code_to_name = {
            "brigade_1": "第一战区旅长",
            "brigade_2": "第二战区旅长",
            "brigade_3": "第三战区旅长",
            "brigade_4": "第四战区旅长",
        }
        self._brigade_name_to_code = {v: k for k, v in self._brigade_code_to_name.items()}
        self._brigade_used_numbers: Dict[str, set] = {}
        self._brigade_free_numbers: Dict[str, List[int]] = {}
        self._ensure_fixed_companies()

    def _gen_name(self) -> str:
        self._seq += 1
        return f"连队-{self._seq}"

    def _normalize_brigade(self, brigade: Optional[str]) -> Optional[str]:
        b = str(brigade or "").strip()
        if not b:
            return None
        if b in self._brigade_code_to_name:
            return b
        if b in self._brigade_name_to_code:
            return self._brigade_name_to_code[b]
        return b

    def _alloc_company_number(self, brigade_code: str) -> int:
        used = self._brigade_used_numbers.setdefault(brigade_code, set())
        free = self._brigade_free_numbers.setdefault(brigade_code, [])
        if free:
            free.sort()
            n = free.pop(0)
            used.add(n)
            return n
        for n in (1, 2, 3):
            if n not in used:
                used.add(n)
                return n
        return 1

    def _free_number_for_name(self, name: str) -> None:
        parts = str(name).split("_")
        if len(parts) >= 3 and parts[0] == "brigade" and parts[2].startswith("company"):
            try:
                bcode = f"brigade_{int(parts[1])}"
            except Exception:
                bcode = None
            try:
                num_str = parts[2].replace("company", "")
                num = int(num_str)
            except Exception:
                num = None
            if bcode and num is not None:
                used = self._brigade_used_numbers.setdefault(bcode, set())
                free = self._brigade_free_numbers.setdefault(bcode, [])
                if num in used:
                    used.discard(num)
                if num not in free:
                    free.append(num)

    def create_company(self, name: Optional[str] = None, brigade: Optional[str] = None, code: Optional[str] = None) -> str:
        bcode = self._normalize_brigade(brigade)
        if bcode:
            num = self._alloc_company_number(bcode)
            base_name = f"{bcode}_company{num}"
        else:
            base_name = name or self._gen_name()
        n = base_name
        if n in self.companies:
            i = 1
            while f"{base_name}-{i}" in self.companies:
                i += 1
            n = f"{base_name}-{i}"
        if code:
            c = str(code)
            if c in self._code_to_name:
                j = 1
                base = c
                while f"{base}-{j}" in self._code_to_name:
                    j += 1
                c = f"{base}-{j}"
        else:
            self._code_seq += 1
            c = f"company_{self._code_seq:03d}"
            while c in self._code_to_name:
                self._code_seq += 1
                c = f"company_{self._code_seq:03d}"
        self._code_to_name[c] = n
        self._name_to_code[n] = c
        self.companies[n] = {"units": set(), "brigade": brigade or bcode or None, "created_at": time.time(), "code": c}
        return n

    def assign_units(self, company: str, unit_ids: List[int]) -> None:
        if company not in self.companies:
            return
        for u in unit_ids or []:
            uid = int(u)
            prev = self.unit_to_company.get(uid)
            if prev and prev != company:
                comp_prev = self.companies.get(prev)
                if comp_prev:
                    comp_prev["units"].discard(uid)
            self.unit_to_company[uid] = company
            self.companies[company]["units"].add(uid)

    def add_units(self, company: str, unit_ids: List[int]) -> None:
        if company not in self.companies:
            return
        for u in unit_ids or []:
            uid = int(u)
            prev = self.unit_to_company.get(uid)
            if prev and prev != company:
                comp_prev = self.companies.get(prev)
                if comp_prev:
                    comp_prev["units"].discard(uid)
            self.unit_to_company[uid] = company
            self.companies[company]["units"].add(uid)

    def remove_unit(self, unit_id: int) -> None:
        uid = int(unit_id)
        cname = self.unit_to_company.get(uid)
        if not cname:
            return
        comp = self.companies.get(cname)
        if not comp:
            return
        comp["units"].discard(uid)
        del self.unit_to_company[uid]

    def dissolve_empty(self, company: str) -> None:
        if company not in self.companies:
            return
        if not self.companies[company]["units"]:
            self._free_number_for_name(company)
            code = self._name_to_code.get(company)
            if code:
                self._code_to_name.pop(code, None)
            self._name_to_code.pop(company, None)
            del self.companies[company]

    # 已删除残部机制，合并相关接口不再提供

    def reassign_company(self, company: str, brigade: Optional[str]) -> None:
        if company not in self.companies:
            return
        bcode = self._normalize_brigade(brigade)
        if not bcode:
            self.companies[company]["brigade"] = brigade or None
            return
        old_name = company
        old_meta = dict(self.companies[old_name])
        code = self._name_to_code.get(old_name)
        target_slots = [f"{bcode}_company{n}" for n in (1, 2, 3)]
        existing = {n: self.companies.get(n) for n in target_slots}
        free_slot = None
        for n in target_slots:
            if existing.get(n) is None:
                free_slot = n
                break
        if free_slot:
            self.companies.pop(old_name, None)
            self.companies[free_slot] = {"units": old_meta.get("units", set()), "brigade": bcode, "created_at": old_meta.get("created_at"), "code": code}
            if code:
                self._code_to_name[code] = free_slot
            self._name_to_code.pop(old_name, None)
            if code:
                self._name_to_code[free_slot] = code
            for uid, cname in list(self.unit_to_company.items()):
                if cname == old_name:
                    self.unit_to_company[uid] = free_slot
        else:
            min_name = None
            min_cnt = None
            for n, meta in existing.items():
                c = len((meta or {}).get("units", set())) if meta else 0
                if min_cnt is None or c < min_cnt:
                    min_cnt = c
                    min_name = n
            dst = min_name
            if dst:
                for u in list(old_meta.get("units", set())):
                    self.add_units(dst, [u])
                self._free_number_for_name(old_name)
                self.companies.pop(old_name, None)
                if code:
                    self._code_to_name[code] = dst
                self._name_to_code.pop(old_name, None)

    def snapshot(self) -> Dict[str, object]:
        out: Dict[str, object] = {"companies": {}, "brigades": {}}
        for name, meta in self.companies.items():
            units = sorted(list(meta["units"]))
            out["companies"][name] = {"units": units, "brigade": meta.get("brigade"), "created_at": meta.get("created_at"), "code": meta.get("code")}
            b = str(meta.get("brigade") or "")
            if b:
                out["brigades"].setdefault(b, []).append(name)
        return out

    def get_company_name_by_code(self, code: str) -> Optional[str]:
        return self._code_to_name.get(str(code))

    def get_companies_for_brigade(self, brigade: str) -> Dict[str, List[int]]:
        res: Dict[str, List[int]] = {}
        targets = {brigade}
        code = self._brigade_name_to_code.get(brigade)
        name = self._brigade_code_to_name.get(brigade)
        if code:
            targets.add(code)
        if name:
            targets.add(name)
        for name_key, meta in self.companies.items():
            bval = str(meta.get("brigade") or "")
            if bval in targets:
                res[name_key] = sorted(list(meta.get("units") or []))
        return res

    def get_company_names_for_brigade(self, brigade: str) -> List[str]:
        names: List[str] = []
        snap = self.snapshot()
        names.extend(list(snap.get("brigades", {}).get(brigade, []) or []))
        bname = self._brigade_code_to_name.get(brigade)
        if bname:
            names.extend(list(snap.get("brigades", {}).get(bname, []) or []))
        bcode = self._brigade_name_to_code.get(brigade)
        if bcode:
            names.extend(list(snap.get("brigades", {}).get(bcode, []) or []))
        names = list(dict.fromkeys(names))
        filtered: List[str] = []
        for n in names:
            meta = snap.get("companies", {}).get(n) or {}
            if len(meta.get("units") or []) > 0:
                filtered.append(n)
        return filtered

    def has_companies(self, brigade: str) -> bool:
        return bool(self.get_company_names_for_brigade(brigade))

    def _ensure_fixed_companies(self) -> None:
        for bcode in ["brigade_1", "brigade_2", "brigade_3", "brigade_4"]:
            used = self._brigade_used_numbers.setdefault(bcode, set())
            for n in (1, 2, 3):
                name = f"{bcode}_company{n}"
                if name not in self.companies:
                    self._code_seq += 1
                    c = f"company_{self._code_seq:03d}"
                    self._code_to_name[c] = name
                    self._name_to_code[name] = c
                    self.companies[name] = {"units": set(), "brigade": bcode, "created_at": time.time(), "code": c}
                used.add(n)
