"""Fixed value sets. Stored as native Postgres enum types, so the database rejects anything else."""

import enum


class QuestionType(str, enum.Enum):
    toggle = "toggle"
    single_choice = "single_choice"
    multi_choice = "multi_choice"
    free_text = "free_text"
    number = "number"


class Subsection(str, enum.Enum):
    introduction = "introduction"
    discovery = "discovery"
    features_functionality = "features_functionality"
    technical_considerations = "technical_considerations"
    integration_design = "integration_design"
    documentation = "documentation"


class Channel(str, enum.Enum):
    ECOM = "ECOM"
    IPP = "IPP"
    MOTO = "MOTO"


class Pillar(str, enum.Enum):
    DIGITAL = "DIGITAL"
    PFS = "PFS"
    UC = "UC"


class Category(str, enum.Enum):
    PAYIN = "PAYIN"
    PAYOUT = "PAYOUT"
    KYC = "KYC"
    PAYFAC = "PAYFAC"
    CAPITAL = "CAPITAL"
    CASHOUT = "CASHOUT"
    REPORTING_RECONCILIATION = "REPORTING_RECONCILIATION"


class Platform(str, enum.Enum):
    PSP = "PSP"
    BALANCE = "BALANCE"


class QuestionStatus(str, enum.Enum):
    active = "active"
    deactivated = "deactivated"


class NodeType(str, enum.Enum):
    question = "question"
    requirement = "requirement"
    constraint = "constraint"
    capability = "capability"
    product = "product"
    integration_design = "integration_design"
    consideration = "consideration"
    asset = "asset"  # details in the asset table


class AssetKind(str, enum.Enum):
    doc_page = "doc_page"
    flow_diagram = "flow_diagram"
    image = "image"


class Lifecycle(str, enum.Enum):
    proposed = "proposed"
    active = "active"
    rejected = "rejected"
    deactivated = "deactivated"
    merged = "merged"


class EdgeType(str, enum.Enum):
    probes = "probes"                      # question -> requirement / constraint / capability
    follow_up = "follow_up"                # question -> question (condition on the answer)
    implies = "implies"                    # requirement -> requirement
    satisfied_by = "satisfied_by"          # requirement / constraint -> product / integration_design
    supports = "supports"                  # product -> capability
    does_not_support = "does_not_support"  # product -> capability
    requires = "requires"                  # product -> product
    alternative_to = "alternative_to"      # product <-> product
    conflicts_with = "conflicts_with"      # requirement <-> product
    composed_of = "composed_of"            # integration_design -> product
    has_consideration = "has_consideration"  # product / integration_design -> consideration
    documented_by = "documented_by"        # any -> asset (doc_page)
    illustrated_by = "illustrated_by"      # product / integration_design -> asset (flow_diagram, image)


class EdgeOrigin(str, enum.Enum):
    curated = "curated"
    derived = "derived"


class SourceType(str, enum.Enum):
    proposal = "proposal"
    question_bank = "question_bank"
    chat = "chat"


class ChatKind(str, enum.Enum):
    """What kind of material the IM shared. Only the kind is kept, never the material."""

    transcript = "transcript"
    brief = "brief"  # a call summary
    notes = "notes"
    email = "email"
    document = "document"


class SpeakerRole(str, enum.Enum):
    merchant = "merchant"
    im = "im"
    other = "other"


class ActType(str, enum.Enum):
    question = "question"
    response = "response"


class InstanceSubtype(str, enum.Enum):
    # questions
    im_discovery = "im_discovery"
    merchant_capability_check = "merchant_capability_check"
    follow_up = "follow_up"
    validation = "validation"
    # responses
    merchant_requirement = "merchant_requirement"
    merchant_constraint = "merchant_constraint"
    merchant_decision = "merchant_decision"
    im_solution = "im_solution"
    im_capability_statement = "im_capability_statement"
    open_item = "open_item"


QUESTION_SUBTYPES = ("im_discovery", "merchant_capability_check", "follow_up", "validation")


class ReviewStatus(str, enum.Enum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"


class LinkRole(str, enum.Enum):
    refers_to = "refers_to"  # instance -> node
    asserts = "asserts"      # instance -> edge


class Polarity(str, enum.Enum):
    supports = "supports"
    contradicts = "contradicts"


class RunStatus(str, enum.Enum):
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
