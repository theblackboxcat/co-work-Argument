# -*- coding: utf-8 -*-
"""Load Skill-V contracts and refuse silent rewrites of semantic identity."""

import copy
import hashlib
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SEED_PATH = os.path.join(ROOT, 'contracts', 'library.json')
REVISED_PATH = os.path.join(ROOT, 'results', 'revised_library.json')


class ContractError(ValueError):
    pass


class PhiLocked(ContractError):
    """Raised when a revision would change a contract's protected phi."""


def phi_digest(text):
    return hashlib.sha256((text or '').encode('utf-8')).hexdigest()


def load(path=None):
    path = path or SEED_PATH
    with open(path, encoding='utf-8') as f:
        lib = json.load(f)
    validate(lib)
    lib['_source_path'] = os.path.abspath(path)
    return lib


def validate(lib):
    if not isinstance(lib, dict):
        raise ContractError('library must be an object')
    contracts = lib.get('contracts')
    if not contracts:
        raise ContractError('library has no contracts')
    lock = lib.get('phi_lock') or {}
    seen = set()
    for c in contracts:
        cid = c.get('id')
        if not cid or cid in seen:
            raise ContractError('duplicate or empty contract id: %r' % cid)
        seen.add(cid)
        phi = c.get('phi')
        if not isinstance(phi, str) or not phi.strip():
            raise ContractError('%s is missing phi' % cid)
        digest = phi_digest(phi)
        if lock.get(cid) != digest:
            raise PhiLocked(
                '%s phi does not match phi_lock (protected semantic identity)'
                % cid)
        if c.get('decision') not in ('speak', 'silence'):
            raise ContractError('%s decision must be speak or silence' % cid)
        if not isinstance(c.get('priority'), int):
            raise ContractError('%s priority must be an int' % cid)
    return lib


def merged_bounds(library, contract):
    bounds = dict(library.get('shared_bounds') or {})
    bounds.update(contract.get('bounds') or {})
    return bounds


def find(library, contract_id):
    for c in library.get('contracts') or []:
        if c.get('id') == contract_id:
            return c
    raise ContractError('unknown contract %s' % contract_id)


def snapshot_phi(library):
    return {c['id']: c['phi'] for c in library['contracts']}


def _assign(library, contract_id, name, value):
    if contract_id == '*shared*':
        bucket = library.setdefault('shared_bounds', {})
        if name not in bucket:
            raise ContractError('unknown shared bound %s' % name)
        old = bucket[name]
        bucket[name] = value
        return old
    contract = find(library, contract_id)
    bucket = contract.setdefault('bounds', {})
    if name not in bucket:
        raise ContractError('unknown bound %s.%s' % (contract_id, name))
    old = bucket[name]
    bucket[name] = value
    contract['version'] = int(contract.get('version') or 1) + 1
    return old


def with_bounds(library, edits, reason, support_ids=None):
    """Return a new library with boundary edits applied. phi is frozen.

    `edits` is a list of (contract_id, bound_name, new_value).
    contract_id '*shared*' addresses shared_bounds.
    """
    original_phi = snapshot_phi(library)
    new = copy.deepcopy(library)
    new.pop('_source_path', None)
    changes = []
    for contract_id, name, value in edits:
        old = _assign(new, contract_id, name, value)
        if old == value:
            continue
        changes.append({
            'contract_id': contract_id,
            'bound': name,
            'from': old,
            'to': value,
        })
    if snapshot_phi(new) != original_phi:
        raise PhiLocked('revision rewrote phi')
    # Re-check digests against the original lock, not a rewritten one.
    validate(new)
    if not changes:
        return new
    new['library_version'] = int(new.get('library_version') or 1) + 1
    new.setdefault('history', []).append({
        'library_version': new['library_version'],
        'reason': reason,
        'support_ids': list(support_ids or []),
        'changes': changes,
    })
    return new


def resolve_library_path(spec=None):
    """seed | revised | filesystem path. Default is the seed library."""
    spec = spec if spec is not None else os.environ.get('SKILLV_LIBRARY', '')
    spec = (spec or '').strip()
    if spec in ('', 'seed'):
        return SEED_PATH
    if spec == 'revised':
        return REVISED_PATH
    return spec
