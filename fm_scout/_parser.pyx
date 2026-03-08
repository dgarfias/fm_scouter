# cython: boundscheck=False, wraparound=False, cdivision=True
"""
Cython-optimized parser for FM24 player data.
Build with: python setup.py build_ext --inplace
"""

cimport cython
from cpython.bytes cimport PyBytes_AS_STRING, PyBytes_GET_SIZE
from libc.string cimport memset

DEF MAX_ATTRS = 54

_ATTR_NAMES = (
    'crossing', 'dribbling', 'finishing', 'heading', 'long_shots',
    'marking', 'passing', 'penalty_taking', 'tackling',
    'first_touch', 'technique', 'corners', 'long_throws', 'free_kick_taking',
    'off_the_ball', 'vision', 'anticipation', 'decisions',
    'positioning', 'flair', 'teamwork', 'work_rate',
    'leadership', 'bravery', 'aggression', 'determination',
    'composure', 'concentration',
    'acceleration', 'strength', 'stamina', 'pace',
    'jumping_reach', 'balance', 'agility', 'natural_fitness',
    'handling', 'aerial_reach', 'command_of_area', 'communication',
    'kicking', 'throwing', 'one_on_ones', 'reflexes',
    'eccentricity', 'rushing_out', 'punching',
    'left_foot', 'right_foot', 'dirtiness', 'consistency',
    'important_matches', 'injury_proneness', 'versatility',
)

_ATTR_NAME_TO_IDX = {name: i for i, name in enumerate(_ATTR_NAMES)}


cdef class CyPlayerAttributes:
    cdef int _values[MAX_ATTRS]

    def __getattr__(self, str name):
        cdef int idx = _ATTR_NAME_TO_IDX.get(name, -1)
        if idx >= 0:
            return self._values[idx]
        raise AttributeError(name)

    def get(self, str name):
        cdef int idx = _ATTR_NAME_TO_IDX.get(name, -1)
        return self._values[idx] if idx >= 0 else 0

    def to_dict(self):
        cdef int i
        return {_ATTR_NAMES[i]: self._values[i] for i in range(MAX_ATTRS)}

    def __repr__(self):
        cdef list parts = []
        cdef int i
        for i in range(MAX_ATTRS):
            if self._values[i] > 0:
                parts.append(f"{_ATTR_NAMES[i]}={self._values[i]}")
        return f"Attributes({', '.join(parts)})"


def parse_combined_data(bytes combined, int pero_in_combined,
                        int pwes, int phes, int pcrp, int pwrp,
                        int pcab, int ppab, int ppos, int patr,
                        int duni, int pdob_day, int pdob_year,
                        int pada, int pcontract, int attr_scale,
                        tuple attr_byte_offsets, tuple position_names,
                        tuple personality_names, int ploan_contract=0xD0):
    cdef const unsigned char *buf = <const unsigned char *>PyBytes_AS_STRING(combined)
    cdef Py_ssize_t buf_len = PyBytes_GET_SIZE(combined)
    cdef const unsigned char *pero = buf + pero_in_combined
    cdef const unsigned char *plao = buf
    cdef Py_ssize_t pero_len = buf_len - pero_in_combined

    cdef unsigned int uid = (<unsigned int *>(pero + duni))[0]
    cdef unsigned short birth_day = (<unsigned short *>(pero + pdob_day))[0]
    cdef unsigned short birth_year = (<unsigned short *>(pero + pdob_year))[0]
    cdef unsigned long long contract_ptr = (<unsigned long long *>(pero + pcontract))[0]

    cdef unsigned long long loan_contract_ptr = 0
    if ploan_contract + 8 <= pero_len:
        loan_contract_ptr = (<unsigned long long *>(pero + ploan_contract))[0]

    cdef short weight = (<short *>(plao + pwes))[0]
    cdef short height = (<short *>(plao + phes))[0]
    cdef short current_rep = (<short *>(plao + pcrp))[0]
    cdef short world_rep = (<short *>(plao + pwrp))[0]
    cdef short ca = (<short *>(plao + pcab))[0]
    cdef short pa = (<short *>(plao + ppab))[0]

    cdef int n_pos = <int>len(position_names)
    cdef dict positions_dict = {}
    cdef int i
    cdef unsigned char pos_val
    for i in range(n_pos):
        pos_val = plao[ppos + i]
        if pos_val > 0:
            positions_dict[position_names[i]] = pos_val

    cdef CyPlayerAttributes attrs = CyPlayerAttributes.__new__(CyPlayerAttributes)
    memset(attrs._values, 0, MAX_ATTRS * sizeof(int))
    cdef int n_attrs = min(<int>len(attr_byte_offsets), MAX_ATTRS)
    cdef int raw_val
    for i in range(n_attrs):
        raw_val = plao[patr + <int>attr_byte_offsets[i]]
        attrs._values[i] = raw_val // attr_scale

    cdef int n_pers = min(<int>len(personality_names), 8)
    cdef dict personality_dict = {}
    for i in range(n_pers):
        personality_dict[personality_names[i]] = pero[pada + i]

    cdef unsigned long long fna_ptr = (<unsigned long long *>(pero + 0x58))[0]
    cdef unsigned long long sna_ptr = (<unsigned long long *>(pero + 0x60))[0]
    cdef unsigned long long cna_ptr = (<unsigned long long *>(pero + 0x68))[0]
    cdef unsigned long long nti_ptr = (<unsigned long long *>(pero + 0x70))[0]

    return (uid, birth_year, birth_day, weight, height, current_rep, world_rep,
            ca, pa, contract_ptr, positions_dict, attrs,
            personality_dict, fna_ptr, sna_ptr, cna_ptr, nti_ptr,
            loan_contract_ptr)


def parse_all_combined(list combined_list, list candidate_info,
                       int pero_in_combined,
                       int pwes, int phes, int pcrp, int pwrp,
                       int pcab, int ppab, int ppos, int patr,
                       int duni, int pdob_day, int pdob_year,
                       int pada, int pcontract, int attr_scale,
                       tuple attr_byte_offsets, tuple position_names,
                       tuple personality_names, int ploan_contract=0xD0):
    cdef list results = []
    cdef int n = <int>len(combined_list)
    cdef int i
    cdef bytes combined
    cdef tuple parsed
    cdef CyPlayerAttributes attrs

    for i in range(n):
        combined = <bytes>combined_list[i]
        parsed = parse_combined_data(
            combined, pero_in_combined,
            pwes, phes, pcrp, pwrp, pcab, ppab, ppos, patr,
            duni, pdob_day, pdob_year, pada, pcontract, attr_scale,
            attr_byte_offsets, position_names, personality_names,
            ploan_contract,
        )

        attrs = <CyPlayerAttributes>parsed[11]
        if (attrs._values[0] == 0 and attrs._values[2] == 0 and
                attrs._values[6] == 0 and attrs._values[8] == 0):
            results.append(None)
            continue

        info = candidate_info[i]
        results.append((info[0], info[1]) + parsed)

    return results


def parse_contract_scalars(bytes cdata, int wage_off, int expiry_off,
                           int flags_off, int transfer_opts_off,
                           int option_years_off, int team_off):
    cdef const unsigned char *buf = <const unsigned char *>PyBytes_AS_STRING(cdata)
    cdef Py_ssize_t buf_len = PyBytes_GET_SIZE(cdata)

    cdef int wage = (<int *>(buf + wage_off))[0]

    cdef unsigned short exp_day = (<unsigned short *>(buf + expiry_off))[0]
    cdef unsigned short exp_year = (<unsigned short *>(buf + expiry_off + 2))[0]
    cdef bint valid_expiry = (exp_year >= 2000 and exp_year < 3000 and
                              exp_day > 0 and exp_day <= 366)

    cdef unsigned int flags = (<unsigned int *>(buf + flags_off))[0]
    cdef unsigned int t_opts = (<unsigned int *>(buf + transfer_opts_off))[0]
    cdef unsigned int o_years = (<unsigned int *>(buf + option_years_off))[0]
    cdef unsigned long long team_ptr = (<unsigned long long *>(buf + team_off))[0]

    return (wage, valid_expiry, flags, t_opts, o_years, team_ptr)
