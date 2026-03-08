from dataclasses import dataclass

@dataclass
class AttributeOffsets:
    TECHNICAL_FIELDS = (
        'crossing', 'dribbling', 'finishing', 'heading', 'long_shots',
        'marking', 'passing', 'penalty_taking', 'tackling',
        'first_touch', 'technique', 'corners', 'long_throws', 'free_kick_taking',
    )
    MENTAL_FIELDS = (
        'off_the_ball', 'vision', 'anticipation', 'decisions',
        'positioning', 'flair', 'teamwork', 'work_rate',
        'leadership', 'bravery', 'aggression', 'determination',
        'composure', 'concentration',
    )
    PHYSICAL_FIELDS = (
        'acceleration', 'strength', 'stamina', 'pace',
        'jumping_reach', 'balance', 'agility', 'natural_fitness',
    )
    GOALKEEPER_FIELDS = (
        'handling', 'aerial_reach', 'command_of_area', 'communication',
        'kicking', 'throwing', 'one_on_ones', 'reflexes',
        'eccentricity', 'rushing_out', 'punching',
    )
    HIDDEN_FIELDS = (
        'left_foot', 'right_foot', 'dirtiness', 'consistency',
        'important_matches', 'injury_proneness', 'versatility',
    )

POSITION_NAMES = (
    'GK', 'SW', 'DL', 'DC', 'DR', 'DM', 'ML', 'MC', 'MR',
    'AML', 'AMC', 'AMR', 'ST', 'WBL', 'WBR',
)

PERSONALITY_NAMES = (
    'Adaptability', 'Ambition', 'Loyalty', 'Pressure',
    'Professionalism', 'Sportsmanship', 'Temperament', 'Controversy',
)

@dataclass
class StructOffsets:
    # Player object offsets (from plao base)
    patr: int = 0x217       # attribute array (54 bytes, raw 1-100 scale)
    ppos: int = 0x208       # position abilities (15 bytes, 1-20 scale)
    pwes: int = 0x1B8       # weight (2 bytes, signed)
    phes: int = 0x1BA       # height (2 bytes, signed)
    pcab: int = 0x200       # current ability (2 bytes)
    ppab: int = 0x202       # potential ability (2 bytes)
    pcrp: int = 0x1FC       # current reputation (2 bytes)
    pwrp: int = 0x1FE       # world reputation (2 bytes)
    pcgv: int = 0x1B0       # guide value

    # Person object offsets (from pero base)
    pfna: int = 0x58        # first name pointer
    psna: int = 0x60        # surname pointer
    pcna: int = 0x68        # common name pointer
    pnti: int = 0x70        # nationality pointer
    pdob_day: int = 0x44    # date of birth day-of-year (2 bytes)
    pdob_year: int = 0x46   # date of birth year (2 bytes)
    pada: int = 0x78        # personality/hidden attributes (8 bytes)
    duni: int = 0x0C        # unique ID (4 bytes)

    # Contract (accessed via pero + pcontract)
    pcontract: int = 0xC8         # pointer to full/parent contract object
    ploan_contract: int = 0xD0    # pointer to loan contract (non-zero = on loan)
    contract_wage: int = 0x18     # weekly wage (4 bytes, raw currency value)
    pffl: int = 0x48              # transfer/loan status flags (uint32 bitfield)
    contract_team: int = 0x10     # full contract -> team pointer
    contract_expiry: int = 0x40   # packed FM date (high16=year, low16=day-of-year)
    contract_transfer_opts: int = 0x56  # transfer offer/clauses option code
    contract_option_years: int = 0x57   # optional extension years

    # Team / Club chain (via contract_team)
    team_club: int = 0x30         # team -> club pointer
    team_competition: int = 0x50  # team -> competition pointer
    club_name_entry: int = 0xC0   # club -> name entry pointer
    competition_name_entry: int = 0x48  # competition -> name entry pointer
    competition_nation: int = 0x60      # competition -> nation pointer
    nation_name: int = 0x18             # nation -> name entry pointer
    nation_continent: int = 0xF0        # nation -> continent pointer
    continent_name: int = 0x18          # continent -> name entry pointer

    # Type offsets (from vtable type info)
    player_offset: int = 0x278
    staff_offset: int = 0xF8
    player_staff_offset: int = 0x138

    # Attribute scale
    attr_scale: int = 5    # raw values / scale = display values (1-20)


ATTR_OFFSETS = AttributeOffsets()
STRUCT_OFFSETS = StructOffsets()
