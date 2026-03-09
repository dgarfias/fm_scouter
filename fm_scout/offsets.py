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
    competition_type: int = 0xF4        # competition type byte (0=top div, 1=div, 8=reserve, 33+=youth)
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

# Attribute byte offsets inside the 54-byte plao.Patr block.
# Source: FM24 CE table (FMCET24.CT, ptrPlayer -> plao.Patr+0x..)
ATTRIBUTE_BYTE_OFFSETS: dict[str, int] = {
    # Technical
    'crossing': 0x00,
    'dribbling': 0x01,
    'finishing': 0x02,
    'heading': 0x03,
    'long_shots': 0x04,
    'marking': 0x05,
    'passing': 0x07,
    'penalty_taking': 0x08,
    'tackling': 0x09,
    'first_touch': 0x16,
    'technique': 0x17,
    'corners': 0x1B,
    'long_throws': 0x1E,
    'free_kick_taking': 0x23,
    # Mental
    'off_the_ball': 0x06,
    'vision': 0x0A,
    'anticipation': 0x11,
    'decisions': 0x12,
    'positioning': 0x14,
    'flair': 0x1A,
    'teamwork': 0x1C,
    'work_rate': 0x1D,
    'leadership': 0x28,
    'bravery': 0x2B,
    'aggression': 0x2D,
    'determination': 0x33,
    'composure': 0x34,
    'concentration': 0x35,
    # Physical
    'acceleration': 0x22,
    'strength': 0x24,
    'stamina': 0x25,
    'pace': 0x26,
    'jumping_reach': 0x27,
    'balance': 0x2A,
    'agility': 0x2E,
    'natural_fitness': 0x32,
    # Goalkeeping
    'handling': 0x0B,
    'aerial_reach': 0x0C,
    'command_of_area': 0x0D,
    'communication': 0x0E,
    'kicking': 0x0F,
    'throwing': 0x10,
    'one_on_ones': 0x13,
    'reflexes': 0x15,
    'eccentricity': 0x1F,
    'rushing_out': 0x20,
    'punching': 0x21,
    # Hidden
    'left_foot': 0x18,
    'right_foot': 0x19,
    'dirtiness': 0x29,
    'consistency': 0x2C,
    'important_matches': 0x2F,
    'injury_proneness': 0x30,
    'versatility': 0x31,
}
