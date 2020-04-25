from __future__ import annotations
import copy
import typing
from typing import Dict, Generic, List, Tuple, TypeVar, Any, Callable, Optional

from sapio.bitcoinlib.messages import COutPoint, CTxInWitness, CTxWitness
from sapio.bitcoinlib.static_types import Amount
from sapio.script.witnessmanager import CTVHash, WitnessManager

from sapio.script.variable import AssignedVariable
from .decorators import HasFinal, final
from .txtemplate import TransactionTemplate
from sapio.contract.contract_base import ContractBase

T = TypeVar("T")
class BindableContract(Generic[T], metaclass=HasFinal):
    # These slots will be extended later on
    __slots__ = ('amount_range', 'specific_transactions', 'witness_manager', 'fields', 'is_initialized', 'init_class')
    witness_manager: WitnessManager
    specific_transactions: List[typing.Tuple[CTVHash, TransactionTemplate]]
    amount_range: Tuple[Amount, Amount]
    fields: T
    is_initialized: bool
    init_class: ContractBase[T]

    class MetaData:
        color = lambda self: "brown"
        label = lambda self: "generic"
    def __getattr__(self, attr) -> AssignedVariable:
        return self.fields.__getattribute__(attr)
    def __setattr__(self, attr, v):
        if attr in self.__slots__:
            super().__setattr__(attr, v)
        elif not self.is_initialized:
            if not hasattr(self, attr):
                raise AssertionError("No Known field for "+attr+" = "+repr(v))
            # TODO Type Check
            setattr(self.fields, attr, v)
        else:
            raise AssertionError("Assigning a value to a field is probably a mistake! ", attr)

    def __init__(self, **kwargs: Any):
        self.is_initialized = False
        self.fields: T = self.__class__.init_class.make_new_fields()
        self.__class__.init_class(self, kwargs)
        self.is_initialized = True

    @final
    def to_json(self):
        return {
            "witness_manager": self.witness_manager.to_json(),
            "transactions": {h: transaction.to_json() for (h, transaction) in self.specific_transactions},
            "min_amount_spent": self.amount_range[0],
            "max_amount_spent": self.amount_range[1],
            "metadata": {
                "color": self.MetaData.color(self),
                "label": self.MetaData.label(self)
            }
        }

    @final
    def bind(self, out: COutPoint):
        # todo: Note that if a contract has any secret state, it may be a hack
        # attempt to bind it to an output with insufficient funds
        color = self.MetaData.color(self)
        output_label = self.MetaData.label(self)

        txns = []
        metadata = []
        for (ctv_hash, txn_template) in self.specific_transactions:
            # todo: find correct witness?
            assert ctv_hash == txn_template.get_ctv_hash()
            tx_label = output_label + ":" + txn_template.label

            tx = txn_template.bind_tx(out)
            txid = tx.sha256
            candidates = [wit for wit in self.witness_manager.witnesses.values() if wit.ctv_hash == ctv_hash]
            # Create all possible candidates
            for wit in candidates:
                t = copy.deepcopy(tx)
                witness = CTxWitness()
                in_witness = CTxInWitness()
                witness.vtxinwit.append(in_witness)
                in_witness.scriptWitness.stack.append(self.witness_manager.program)
                in_witness.scriptWitness.stack.extend(wit.witness)
                t.wit = witness
                txns.append(t)
                utxo_metadata = [{'color': md.color, 'label': md.label} for md in txn_template.outputs_metadata]
                metadata.append(
                    {'color': color, 'label': tx_label, 'utxo_metadata': utxo_metadata})
            for (idx, (_, contract)) in enumerate(txn_template.outputs):
                new_txns, new_metadata = contract.bind(COutPoint(txid, idx))
                txns.extend(new_txns)
                metadata.extend(new_metadata)
        return txns, metadata
