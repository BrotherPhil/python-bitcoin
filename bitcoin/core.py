#!/usr/bin/env python
# -*- coding: utf-8 -*-

#
# Copyright © 2012-2013 by its contributors. See AUTHORS for details.
#
# Distributed under the MIT/X11 software license, see the accompanying
# file LICENSE or http://www.opensource.org/licenses/mit-license.php.
#

import numbers
from struct import pack, unpack

from python_patterns.utils.decorators import Property

from .crypto import merkle
from .mixins import HashableMixin, SerializableMixin
from .numeric import mpq
from .script import Script
from .serialize import (
    serialize_varchar, deserialize_varchar,
    serialize_hash, deserialize_hash,
    serialize_list, deserialize_list)
from .utils import StringIO, target_from_compact

__all__ = [
    'ChainParameters',
    'OutPoint',
    'Input',
    'Output',
    'Transaction',
    'Merkle',
    'Block',
]

# ===----------------------------------------------------------------------===

from collections import namedtuple

ChainParameters = namedtuple('ChainParameters', ['magic', 'port', 'genesis',
    'testnet', 'max_value', 'transient_reward', 'transient_budget',
    'perpetual_reward', 'perpetual_budget', 'fee_budget', 'maximum_target',
    'next_target', 'alert_keys','checkpoints', 'features'])

# ===----------------------------------------------------------------------===

class OutPoint(SerializableMixin):
    def __init__(self, hash=0, n=0xffffffff, *args, **kwargs):
        super(OutPoint, self).__init__(*args, **kwargs)
        self.hash = hash
        self.n = n

    def serialize(self):
        result  = serialize_hash(self.hash, 32)
        result += pack('<I', self.n)
        return result
    @classmethod
    def deserialize(cls, file_):
        initargs = {}
        initargs['hash'] = deserialize_hash(file_, 32)
        initargs['n'] = unpack('<I', file_.read(4))[0]
        return cls(**initargs)

    def __eq__(self, other):
        return self.hash==other.hash and self.n==other.n
    def __repr__(self):
        return 'OutPoint(hash=%064x, n=%d)' % (
            self.hash,
            self.n==0xffffffff and -1 or self.n)

    def set_null(self):
        self.hash = 0
        self.n = 0xffffffff
    def is_null(self):
        return self.hash==0 and self.n==0xffffffff

# ===----------------------------------------------------------------------===

class Input(SerializableMixin):
    def __init__(self, prevout=None, scriptSig=None, nSequence=0xffffffff,
                 *args, **kwargs):
        if prevout is None:
            prevout = self.deserialize_prevout(StringIO('\x00'*32 + '\xff'*4))
        if scriptSig is None:
            scriptSig = kwargs.pop('coinbase', Script())
        super(Input, self).__init__(*args, **kwargs)
        self.prevout = prevout
        self.scriptSig = scriptSig
        self.nSequence = nSequence

    def serialize(self):
        result = self.prevout.serialize()
        if hasattr(self.scriptSig, 'serialize'):
            result += self.scriptSig.serialize()
        else:
            result += serialize_varchar(self.scriptSig) # <-- coinbase
        result += pack('<I', self.nSequence)
        return result
    @staticmethod
    def deserialize_prevout(file_):
        return OutPoint.deserialize(file_)
    @classmethod
    def deserialize(cls, file_):
        initargs = {}
        initargs['prevout'] = cls.deserialize_prevout(file_)
        str_ = deserialize_varchar(file_) # <-- coinbase?
        initargs['nSequence'] = unpack('<I', file_.read(4))[0]
        if initargs['prevout'].is_null() and initargs['nSequence']==0xffffffff:
            initargs['coinbase'] = str_
        else:
            initargs['scriptSig'] = Script.deserialize(StringIO(serialize_varchar(str_)))
        return cls(**initargs)

    def __eq__(self, other):
        return (self.prevout   == other.prevout   and
                self.scriptSig == other.scriptSig and
                self.nSequence == other.nSequence)
    def __repr__(self):
        nSequence_str = (self.nSequence!=0xffffffff
            and ', nSequence=%d' % self.nSequence
             or '')
        return 'Input(prevout=%s, %s=%s%s)' % (
            repr(self.prevout),
            self.prevout.is_null() and 'coinbase' or 'scriptSig',
            repr(self.scriptSig),
            nSequence_str)

    def is_final(self):
        return self.nSequence==0xffffffff

# ===----------------------------------------------------------------------===

class Output(SerializableMixin):
    def __init__(self, nValue=0, scriptPubKey=None, *args, **kwargs):
        if scriptPubKey is None:
            scriptPubKey = Script()
        super(Output, self).__init__(*args, **kwargs)
        self.nValue = nValue
        self.scriptPubKey = scriptPubKey

    def serialize(self):
        result  = pack('<Q', self.nValue)
        result += self.scriptPubKey.serialize()
        return result
    @classmethod
    def deserialize(cls, file_):
        initargs = {}
        initargs['nValue'] = unpack('<Q', file_.read(8))[0]
        initargs['scriptPubKey'] = Script.deserialize(file_)
        return cls(**initargs)

    def __eq__(self, other):
        return (self.nValue == other.nValue and
            self.scriptPubKey == other.scriptPubKey)
    def __repr__(self):
        return 'Output(nValue=%d.%08d, scriptPubKey=%s)' % (
            self.nValue // 100000000,
            self.nValue % 100000000,
            repr(self.scriptPubKey))

# ===----------------------------------------------------------------------===

class Transaction(SerializableMixin, HashableMixin):
    def __init__(self, nVersion=1, vin=None, vout=None, nLockTime=0,
                 nRefHeight=0, *args, **kwargs):
        if vin is None: vin = []
        if vout is None: vout = []
        super(Transaction, self).__init__(*args, **kwargs)
        self.nVersion = nVersion
        self.vin_create()
        for tin in vin:
            self.vin.append(tin)
        self.vout_create()
        for tout in vout:
            self.vout.append(tout)
        self.nLockTime = nLockTime
        self.nRefHeight = nRefHeight

    def vin_create(self):
        self.vin = []
    vin_clear = vin_create

    def vout_create(self):
        self.vout = []
    vout_clear = vout_create

    def serialize(self):
        if self.nVersion not in (1,2):
            raise NotImplementedError
        result  = pack('<I', self.nVersion)
        result += serialize_list(self.vin, lambda i:i.serialize())
        result += serialize_list(self.vout, lambda o:o.serialize())
        result += pack('<I', self.nLockTime)
        if self.nVersion==2:
            result += pack('<I', self.nRefHeight)
        return result
    @staticmethod
    def deserialize_input(file_, *args, **kwargs):
        return Input.deserialize(file_, *args, **kwargs)
    @staticmethod
    def deserialize_output(file_, *args, **kwargs):
        return Output.deserialize(file_, *args, **kwargs)
    @classmethod
    def deserialize(cls, file_):
        initargs = {}
        initargs['nVersion'] = unpack('<I', file_.read(4))[0]
        if initargs['nVersion'] not in (1,2):
            raise NotImplementedError
        initargs['vin'] = list(deserialize_list(file_, lambda f:cls.deserialize_input(f)))
        initargs['vout'] = list(deserialize_list(file_, lambda f:cls.deserialize_output(f)))
        initargs['nLockTime'] = unpack('<I', file_.read(4))[0]
        if initargs['nVersion']==2:
            initargs['nRefHeight'] = unpack('<I', file_.read(4))[0]
        else:
            initargs['nRefHeight'] = 0
        return cls(**initargs)

    def __eq__(self, other):
        if (self.nVersion   != other.nVersion  or
            self.nLockTime  != other.nLockTime or
            self.nRefHeight != other.nRefHeight):
            return False
        if list(self.vin) != list(other.vin):
            return False
        if list(self.vout) != list(other.vout):
            return False
        return True
    def __repr__(self):
        nRefHeight_str = (self.nVersion==2
            and ', nRefHeight=%d' % self.nRefHeight
             or '')
        return ('Transaction(nVersion=%d, '
                            'vin=%s, '
                            'vout=%s, '
                            'nLockTime=%d%s)' % (
            self.nVersion,
            repr(self.vin),
            repr(self.vout),
            self.nLockTime,
            nRefHeight_str))

    def is_final(self, block_height, block_time):
        if self.nLockTime < LOCKTIME_THRESHOLD:
            if block_height is None:
                # FIXME: nBlockHeight = nBestHeight
                raise ValueError(
                    u"block_height required but missing")
            if self.nLockTime < block_height:
                return False
        else:
            if block_time is None:
                # FIXME: nBlockTime = GetAdjustedTime()
                raise ValueError(
                    u"block_time required but missing")
            if self.nLockTime < block_time:
                return False
        for txin in self.vin:
            if not txin.is_final():
                return False
        return True

    def is_newer_than(self, other):
        vin_count = len(self.vin)
        if vin_count != len(other.vin):
            return False
        # FIXME: this could be made more pythonic...
        newer = False
        lowest = 0xffffffff
        for idx in xrange(vin_count):
            self_vin = self.vin[idx]
            other_vin = other.vin[idx]
            if self_vin.prevout != other_vin.prevout:
                return False
            if self_vin.nSequence != other_vin.nSequence:
                if self_vin.nSequence <= lowest:
                    newer = False
                    lowest = self_vin.nSequence
                if other_vin.nSequence < lowest:
                    newer = True
                    lowest = other_vin.nSequence
        return newer

    def is_coinbase(self):
        return len(self.vin)==1 and self.vin[0].prevout.is_null()

# ===----------------------------------------------------------------------===

class Merkle(SerializableMixin, HashableMixin):
    def __init__(self, children=None, *args, **kwargs):
        if children is None: children = []
        super(Merkle, self).__init__(*args, **kwargs)
        self.children_create()
        for child in children:
            if hasattr(child, 'hash'):
                child = child.hash
            self.children.append(child)

    def children_create(self):
        self.children = []
    children_clear = children_create

    def serialize(self):
        # detect version=2 (explicit) merkle trees
        if any(map(lambda h:not isinstance(h, numbers.Integral), self.children)):
            raise NotImplementedError
        return serialize_list(self.children, lambda x:serialize_hash(x, 32))
    @classmethod
    def deserialize(cls, file_):
        return cls(deserialize_list(file_, lambda x:deserialize_hash(x, 32)))

    def hash__getter(self):
        return merkle(self.children)

    def __eq__(self, other):
        return map(merkle, self.children) == map(merkle, other.children)
    def __repr__(self):
        return ''.join(['Merkle([', ', '.join(map(repr, self.children)), '])'])

# ===----------------------------------------------------------------------===

class Block(SerializableMixin, HashableMixin):
    def __init__(self, chain, nVersion=1, hashPrevBlock=0, hashMerkleRoot=None,
                 nTime=0, nBits=0x1d00ffff, nNonce=0, vtx=None, *args, **kwargs):
        if None not in (hashMerkleRoot, vtx):
            if hashMerkleRoot != merkle(vtx):
                raise ValueError(
                    u"hashMerkleRoot does not match merkle(vtx); are you "
                    u"sure you know what you're doing?")
        else:
            if vtx            is None: vtx            = []
            if hashMerkleRoot is None: hashMerkleRoot = merkle(vtx)
        super(Block, self).__init__(*args, **kwargs)

        self.chain = chain
        self.nVersion = nVersion
        self.hashPrevBlock = hashPrevBlock
        self.hashMerkleRoot = hashMerkleRoot
        self.nTime = nTime
        self.nBits = nBits
        self.nNonce = nNonce

    @Property
    def merkleTree():
        def fget(self):
            return self.chain.merkles.get(self.hashMerkleRoot, None)
        def fset(self, merkleTree):
            hashMerkleRoot = merkle(merkleTree)
            if not isinstance(hashMerkleRoot, numbers.Integral):
                raise ValueError(
                    u"Merkle-tree could not be reduced to root hash value\n"
                    u"    merkleTree:     %(merkleTree)s\n"
                    u"    hashMerkleRoot: %(hashMerkleRoot)s" % {
                        'merkleTree': repr(merkleTree),
                        'hashMerkleRoot': repr(hashMerkleRoot),
                    })
            self.hashMerkleRoot = hashMerkleRoot
        def fdel(self):
            self.hashMerkleRoot = 0L
        return locals()

    def serialize(self, mode=None):
        if mode is None:
            mode = 'header'
        if mode not in ('full', 'header'):
            raise ValueError(u"unrecognized block serialization mode")
        if self.nVersion not in (1,2):
            raise NotImplementedError
        result  = pack('<I', self.nVersion)
        result += serialize_hash(self.hashPrevBlock, 32)
        result += serialize_hash(self.hashMerkleRoot, 32)
        result += pack('<I', self.nTime)
        result += pack('<I', self.nBits)
        result += pack('<I', self.nNonce)
        if mode in ('header',):
            return result
        merkleTree = self.merkleTree
        if merkleTree is None:
            raise self.ValidationError(
                u"block-transaction Merkle-tree missing; cannot serialize "
                u"transaction list without the Merkle-tree\n"
                u"    hashMerkleRoot: %064x" % self.hashMerkleRoot)
        vtxid = [txid for txid in merkle_iter(merkleTree)]
        vtx = [self.chain.transactions.get(txid, None) for txid in vtxid]
        if None in vtx:
            desc = (
                u"missing transactions; the following transactions from the "
                u"Merkle-tree are missing unaccounted for\n"
                u"    txid: ")
            desc += u"\n    txid: ".join(
                vtxid[idx]
                for idx, tx in enumerate(vtx)
                if tx is None)
            raise self.ValidationError(desc)
        result += serialize_list(vtx, lambda t:t.serialize())
        return result
    def __bytes__(self):
        return self.serialize(mode='header')
    @staticmethod
    def deserialize_transaction(file_, *args, **kwargs):
        return Transaction.deserialize(file_, *args, **kwargs)
    @classmethod
    def deserialize(cls, chain, file_, mode=None):
        if mode is None:
            mode = 'header'
        if mode not in ('full', 'header'):
            raise ValueError(u"unrecognized block serialization mode")
        initargs = {}
        initargs['nVersion'] = unpack('<I', file_.read(4))[0]
        if initargs['nVersion'] not in (1,2):
            raise NotImplementedError
        initargs['hashPrevBlock'] = deserialize_hash(file_, 32)
        initargs['hashMerkleRoot'] = deserialize_hash(file_, 32)
        initargs['nTime'] = unpack('<I', file_.read(4))[0]
        initargs['nBits'] = unpack('<I', file_.read(4))[0]
        initargs['nNonce'] = unpack('<I', file_.read(4))[0]
        if mode in ('header',):
            return cls(chain, **initargs)
        initargs['vtx'] = list(deserialize_list(file_, lambda f:cls.deserialize_transaction(f)))
        return cls(chain, **initargs)

    def __eq__(self, other):
        return (self.nVersion       == other.nVersion       and
                self.hashPrevBlock  == other.hashPrevBlock  and
                self.hashMerkleRoot == other.hashMerkleRoot and
                self.nTime          == other.nTime          and
                self.nBits          == other.nBits          and
                self.nNonce         == other.nNonce)
    def __repr__(self):
        return ('Block(nVersion=%d, '
                      'hashPrevBlock=0x%064x, '
                      'hashMerkleRoot=0x%064x, '
                      'nTime=%s, '
                      'nBits=0x%08x, '
                      'nNonce=0x%08x)' % (
            self.nVersion,
            self.hashPrevBlock,
            self.hashMerkleRoot,
            self.nTime,
            self.nBits,
            self.nNonce))

    @Property
    def difficulty():
        def fget(self):
            return mpq(2**256-1, target_from_compact(self.nBits))
        return locals()

#
# End of File
#
