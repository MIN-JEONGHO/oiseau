"""단위 규칙(spec 7.1). 별칭 표준화·종류·환산·비교 결과를 고정 표로 제공한다.

판정 엔진은 목표 단위와 기준 단위를 `normalize_unit`으로 표준 표기로 바꾼 뒤
- 같은 글자(빈 글끼리, "단"·"축" 같은 것 포함)이면 그대로 비교하고,
- 다르면 같은 종류이고 고정 환산표로 환산할 수 있을 때만 `convert`로 환산해 비교한다.
`compare_units`가 'same'|'convertible'|'different_kind'|'not_convertible'을 구분해 돌려준다.

온도(℃·K·℉)는 오프셋이 있어 환산하지 않는다. 같은 글자일 때만 비교한다.
비율(%·ppm·ppi·dpi·wt.% 등)도 글자가 같을 때만 비교한다(종류는 같지만 환산하지 않는다).
년은 365일, 일은 24시간으로 둔다(고정 환산표의 가정).
환산 인자는 정확한 분수로 다룬다(1.3.3). 3600·60으로 나누는 단위는 표에 '분자/분모'로 적고, 환산한 값이 유한 소수이면
한 자리도 틀리지 않게 돌려준다(2160 km/h = 600 m/s). 끝나지 않는 소수일 때만 계산 정밀도(28자리)에서 반올림한다.
rad 계열은 원주율이 들어가 정확한 분수가 없으므로 어림값 그대로다.
데이터량 접두어는 10진(1 kB = 1000 byte)으로 둔다.

표는 모두 모듈 상수이며 조정할 수 있다. 모르는 단위는 글자 그대로(strip) 돌려주고 종류는 None이다.
"""
from decimal import Decimal
from fractions import Fraction

MICRO = "μ"  # U+03BC. 마이크로 기호 U+00B5(µ)는 이것으로 통일한다.

# 종류별 기준 단위와 환산 인자(표준 표기 → (종류, 기준 단위 기준 배수)). 배수 None은 환산하지 않는 단위.
# 배수는 10진수 글자이거나 '분자/분모'(둘 다 10진수 글자)다. _factor가 정확한 분수로 읽는다.
# SI 접두어가 붙는 단위는 아래 _SI_BASES에서 만든다.
_SI_PREFIXES = {
    "n": "0.000000001", "μ": "0.000001", "m": "0.001", "c": "0.01", "": "1", "k": "1000", "M": "1000000",
    "G": "1000000000", "T": "1000000000000",
}
# (기준 단위 글자, 종류, 허용 접두어, 종류 기준 단위에 대한 배수). byte는 bit 기준 8, Wh는 J 기준 3600.
_SI_BASES = (
    ("m", "length", ("n", "μ", "m", "c", "", "k")),
    ("g", "mass", ("μ", "m", "", "k")),
    ("Hz", "frequency", ("", "k", "M", "G", "T")),
    ("W", "power", ("n", "μ", "m", "", "k", "M", "G")),
    ("J", "energy", ("μ", "m", "", "k", "M", "G")),
    ("Wh", "energy", ("", "k", "M", "G"), "3600"),
    ("Pa", "pressure", ("m", "", "k", "M", "G")),
    ("A", "current", ("μ", "m", "", "k")),
    ("V", "voltage", ("μ", "m", "", "k", "M")),
    ("L", "volume", ("μ", "m", "", "k")),
    ("N", "force", ("m", "", "k", "M")),
    ("B", "data", ("", "k", "M", "G", "T"), "8"),
    ("bit", "data", ("", "k", "M", "G", "T"), "1"),
    ("bps", "data_rate", ("", "k", "M", "G", "T")),
    ("F", "capacitance", ("n", "μ", "m", "")),
    ("Ω", "resistance", ("m", "", "k", "M")),
    ("H", "inductance", ("n", "μ", "m", "")),
)
# 접두어 단위가 아닌 것(표준 표기 → (종류, 배수)). 배수 None은 같은 글자일 때만 비교.
_OTHER_UNITS = {
    # 시간(기준 초)
    "초": ("time", "1"), "분": ("time", "60"), "시간": ("time", "3600"), "일": ("time", "86400"),
    "주": ("time", "604800"), "년": ("time", "31536000"), "ms": ("time", "0.001"), "μs": ("time", "0.000001"),
    "ns": ("time", "0.000000001"),
    # 길이(기준 m)
    "인치": ("length", "0.0254"), "ft": ("length", "0.3048"), "Å": ("length", "0.0000000001"),
    # 질량(기준 g)
    "t": ("mass", "1000000"), "lb": ("mass", "453.59237"),
    # 압력(기준 Pa)
    "bar": ("pressure", "100000"), "mbar": ("pressure", "100"), "hPa": ("pressure", "100"), "atm": ("pressure", "101325"),
    "psi": ("pressure", "4.4482216152605/0.00064516"), "Torr": ("pressure", "101325/760"),
    # 에너지(기준 J). Wh 계열은 _SI_BASES에서 J 기준 3600배로 만든다(1 Wh = 3600 J).
    "eV": ("energy", "0.0000000000000000001602176634"), "cal": ("energy", "4.184"), "kcal": ("energy", "4184"),
    # 힘(기준 N)
    "lbf": ("force", "4.4482216152605"), "kgf": ("force", "9.80665"),
    # 밀도(기준 kg/m3)
    "kg/m3": ("density", "1"), "g/cm3": ("density", "1000"), "g/mL": ("density", "1000"), "kg/L": ("density", "1000"),
    "g/L": ("density", "1"),
    # 에너지밀도(기준 Wh/kg, Wh/L)
    "Wh/kg": ("energy_density_mass", "1"), "kWh/kg": ("energy_density_mass", "1000"),
    "Wh/L": ("energy_density_volume", "1"), "kWh/L": ("energy_density_volume", "1000"),
    # 전력밀도·전류밀도·정전용량밀도
    "W/kg": ("power_density_mass", "1"), "kW/kg": ("power_density_mass", "1000"),
    "A/cm2": ("current_density", "1"), "mA/cm2": ("current_density", "0.001"),
    "μF/mm3": ("capacitance_density", "1"),
    # 속도(기준 m/s)
    "m/s": ("speed", "1"), "km/h": ("speed", "1/3.6"), "km/s": ("speed", "1000"),
    "kn": ("speed", "1852/3600"), "Mach": ("speed", None),
    # 넓이·부피(기준 m2, m3)
    "m2": ("area", "1"), "cm2": ("area", "0.0001"), "mm2": ("area", "0.000001"), "km2": ("area", "1000000"),
    "m3": ("volume", "1000"), "cm3": ("volume", "0.001"), "mm3": ("volume", "0.000001"),
    # 온도: 환산하지 않는다(오프셋). 같은 글자일 때만 비교.
    "℃": ("temperature", None), "K": ("temperature", None), "℉": ("temperature", None),
    # 비율: 같은 글자일 때만 비교.
    "%": ("ratio", None), "ppm": ("ratio", None), "ppb": ("ratio", None), "ppi": ("ratio", None),
    "dpi": ("ratio", None), "wt.%": ("ratio", None), "vol.%": ("ratio", None), "at.%": ("ratio", None),
    "mol.%": ("ratio", None), "dB": ("ratio", None), "dBm": ("ratio", None),
    # 각도
    "°": ("angle", "1"), "rad": ("angle", "57.29577951308232"), "mrad": ("angle", "0.05729577951308232"),
    "μrad": ("angle", "0.00005729577951308232"),
    # 회전수·기타
    "rpm": ("rotation", "1"), "rps": ("rotation", "60"),
    "FLOPS": ("compute", "1"), "GFLOPS": ("compute", "1000000000"), "TFLOPS": ("compute", "1000000000000"),
    "PFLOPS": ("compute", "1000000000000000"),
    # 고시 원문에서 추가로 확인된 단위(2026-11-05 기준값 읽기 보고). 같은 종류끼리만 환산.
    "WT": ("weighted_teraflops", "1"),  # 이중용도 4A003 가중 TeraFLOPS
    "마력": ("power", "735.49875"),  # PS 기준(W)
    "hp": ("power", "745.69987158227022"),
    "mAh/g": ("specific_capacity", "1"), "Ah/kg": ("specific_capacity", "1"),
    "kJ/kg": ("specific_energy", "1000"), "MJ/kg": ("specific_energy", "1000000"), "J/kg": ("specific_energy", "1"),
    "GJ/m3": ("energy_density_volume_j", "1"), "kJ/m3": ("energy_density_volume_j", "0.000001"),
    "mm/s": ("speed", "0.001"), "mm/year": ("speed", None), "μm/h": ("speed", None),
    "m3/s": ("flow", "1"), "m3/min": ("flow", "1/60"), "m3/h": ("flow", "1/3600"),
    "L/min": ("flow", "0.001/60"), "L/h": ("flow", "0.001/3600"), "cm3/min": ("flow", "0.000001/60"),
    "kg/h": ("mass_flow", "1"), "kg/min": ("mass_flow", "60"), "kg/s": ("mass_flow", "3600"),
    "Pa/h": ("pressure_rate", "1"),
    "meq/g": ("equivalent_mass", "1"), "poise": ("viscosity", "1"), "cP": ("viscosity", "0.01"),
    "m2/g": ("specific_area", "1"),
    "H/m": ("permeability", "1"), "VA": ("apparent_power", "1"), "kVA": ("apparent_power", "1000"),
    "A/mm2": ("current_density", "100"), "mA/mm2": ("current_density", "0.1"), "A/μs": ("current_rate", "1"),
    "GBq/kg": ("specific_activity", "1"), "S/m": ("conductivity", "1"), "Ω/square": ("sheet_resistance", "1"),
    "ohm-cm": ("resistivity", "1"), "T": ("magnetic_flux_density", "1"), "mT": ("magnetic_flux_density", "0.001"),
    "g/m": ("linear_density", "1"), "GB/s": ("data_rate_bytes", "1000000000"), "MB/s": ("data_rate_bytes", "1000000"),
    "GSPS": ("sample_rate", "1000000000"), "MSPS": ("sample_rate", "1000000"),
    "keV": ("energy", "0.0000000000000001602176634"), "MeV": ("energy", "0.0000000000001602176634"),
    "ps": ("time", "0.000000000001"),
    "arcsec": ("angle", "1/3600"), "°/s": ("angular_rate", "1"), "°/h": ("angular_rate", "1/3600"),
    "dBc": ("ratio", None), "dBm/Hz": ("ratio", None), "μC/mm2": ("charge_density", "1"),
    "g-mm/kg": ("unbalance", "1"), "mg/m3": ("concentration", "1"), "mmol": ("amount", "1"),
    "옥타브": ("octave", "1"), "qubit": ("count", None),
    "해리": ("length", "1852"), "Nm": ("torque", "1"), "kNm": ("torque", "1000"),
    "Ns": ("impulse", "1"), "kNs": ("impulse", "1000"), "MNs": ("impulse", "1000000"),
    "kNs/kg": ("specific_impulse_mass", "1"), "kN/kg": ("thrust_to_weight", "1"),
    "kW/m3": ("power_density_volume", "1"), "W/m3": ("power_density_volume", "0.001"),
    "μg(가속도)": ("acceleration_g", "0.000001"), "°/s2": ("angular_acceleration", "1"),
    "Gal": ("acceleration", "1"), "mGal": ("acceleration", "0.001"), "μGal": ("acceleration", "0.000001"),
    "nT": ("magnetic_flux_density", "0.000000001"), "pT": ("magnetic_flux_density", "0.000000000001"),
    "fT": ("magnetic_flux_density", "0.000000000000001"), "nT/m": ("magnetic_gradient", "1"),
    "W/cm2": ("irradiance", "1"), "kW/cm2": ("irradiance", "1000"), "J/cm2": ("fluence", "1"),
    "frame/s": ("frame_rate", "1"), "m2/s": ("kinematic", "1"), "mm/μs": ("speed", "1000"),
    "μA/lm": ("photosensitivity", "1"), "mA/W": ("responsivity", "1"), "rad/s2": ("angular_acceleration_rad", "1"),
    "kg/m2": ("areal_density", "1"), "nV": ("voltage", "0.000000001"),
}


def _build_standard_units():
    table = {}
    for base, kind, prefixes, *scale in _SI_BASES:
        multiplier = Decimal(scale[0]) if scale else Decimal(1)
        for prefix in prefixes:
            table[prefix + base] = (kind, str(Decimal(_SI_PREFIXES[prefix]) * multiplier))
    for unit, (kind, factor) in _OTHER_UNITS.items():
        if unit in table:
            raise ValueError(f"단위 표 중복: {unit}")
        table[unit] = (kind, factor)
    return table


# 표준 표기 → (종류, 기준 단위 배수 문자열 또는 None)
STANDARD_UNITS = _build_standard_units()

# 원문 표기 → 표준 표기. 여기 있는 별칭만 같은 단위로 인정한다(검증 규칙 3).
ALIASES = {
    # 길이
    "㎚": "nm", "나노": "nm", "나노미터": "nm", "나노m": "nm",
    "㎛": "μm", "um": "μm", "µm": "μm", "마이크로": "μm", "마이크로미터": "μm", "micron": "μm",
    "㎜": "mm", "밀리미터": "mm", "밀리": "mm",
    "㎝": "cm", "센티미터": "cm", "센티": "cm",
    "미터": "m", "㎞": "km", "Km": "km", "KM": "km", "킬로미터": "km",
    "in.": "인치", "inch": "인치", "inches": "인치",
    "feet": "ft", "foot": "ft", "피트": "ft", "옹스트롬": "Å", "A°": "Å",
    # 시간
    "s": "초", "sec": "초", "second": "초", "seconds": "초",
    "min": "분", "minute": "분", "minutes": "분",
    "h": "시간", "hr": "시간", "hrs": "시간", "hour": "시간", "hours": "시간",
    "d": "일", "day": "일", "days": "일",
    "wk": "주", "week": "주", "weeks": "주",
    "y": "년", "yr": "년", "yrs": "년", "year": "년", "years": "년",
    "밀리초": "ms", "msec": "ms", "마이크로초": "μs", "us": "μs", "µs": "μs", "나노초": "ns",
    # 질량
    "㎏": "kg", "킬로그램": "kg", "㎎": "mg", "밀리그램": "mg", "㎍": "μg", "ug": "μg", "µg": "μg",
    "그램": "g", "gram": "g", "톤": "t", "ton": "t", "tons": "t", "tonne": "t", "tonnes": "t", "ton(metric)": "t",
    "lbs": "lb", "파운드": "lb",
    # 주파수
    "㎐": "Hz", "㎑": "kHz", "㎒": "MHz", "㎓": "GHz", "㎔": "THz", "헤르츠": "Hz",
    # 전력·에너지
    "㎾": "kW", "㎿": "MW", "와트": "W", "킬로와트": "kW", "메가와트": "MW",
    "㎉": "kcal", "줄": "J", "킬로줄": "kJ", "㎾h": "kWh", "킬로와트시": "kWh", "와트시": "Wh",
    "㎿h": "MWh",
    # 압력
    "㎩": "Pa", "㎪": "kPa", "㎫": "MPa", "㎬": "GPa", "파스칼": "Pa", "메가파스칼": "MPa",
    "mmHg": "Torr", "torr": "Torr", "기압": "atm",
    # 힘
    "뉴턴": "N", "㎸": "kV", "㎹": "MV", "㎷": "mV", "㎶": "μV", "uV": "μV", "µV": "μV",
    "㎃": "mA", "㎂": "μA", "uA": "μA", "µA": "μA", "암페어": "A", "볼트": "V", "킬로볼트": "kV",
    # 부피
    "리터": "L", "l": "L", "ℓ": "L", "liter": "L", "litre": "L", "liters": "L", "litres": "L",
    "㎖": "mL", "ml": "mL", "밀리리터": "mL", "㎕": "μL", "uL": "μL", "µL": "μL", "㎘": "kL",
    "㎥": "m3", "m³": "m3", "㎤": "cm3", "cm³": "cm3", "cc": "cm3", "㎣": "mm3", "mm³": "mm3",
    "㎡": "m2", "m²": "m2", "㎠": "cm2", "cm²": "cm2", "㎟": "mm2", "mm²": "mm2", "㎢": "km2", "km²": "km2",
    # 밀도·복합 단위
    "g/cc": "g/cm3", "g/㎤": "g/cm3", "g/cm³": "g/cm3", "kg/㎥": "kg/m3", "kg/m³": "kg/m3", "g/ml": "g/mL",
    "kg/l": "kg/L", "g/l": "g/L",
    "Wh/㎏": "Wh/kg", "wh/kg": "Wh/kg", "kWh/㎏": "kWh/kg", "Wh/l": "Wh/L", "Wh/ℓ": "Wh/L", "Wh/리터": "Wh/L",
    "W/㎏": "W/kg", "A/㎠": "A/cm2", "A/cm²": "A/cm2", "mA/㎠": "mA/cm2", "mA/cm²": "mA/cm2",
    "uF/mm3": "μF/mm3", "µF/mm3": "μF/mm3", "μF/mm³": "μF/mm3", "uF/mm³": "μF/mm3", "μF/㎣": "μF/mm3",
    "uF": "μF", "µF": "μF", "uH": "μH", "µH": "μH", "ohm": "Ω", "Ohm": "Ω", "옴": "Ω",
    "kohm": "kΩ", "Mohm": "MΩ",
    # 속도
    "m/sec": "m/s", "㎧": "m/s", "㎞/h": "km/h", "kph": "km/h", "km/hr": "km/h", "㎞/s": "km/s", "knot": "kn",
    "knots": "kn", "노트": "kn", "마하": "Mach", "mach": "Mach",
    # 온도(환산 없음, 글자만 통일)
    "°C": "℃", "degC": "℃", "섭씨": "℃", "켈빈": "K", "°K": "K", "°F": "℉", "degF": "℉", "화씨": "℉",
    # 비율
    "퍼센트": "%", "percent": "%", "％": "%", "wt%": "wt.%", "중량%": "wt.%", "중량 %": "wt.%",
    "vol%": "vol.%", "부피%": "vol.%", "at%": "at.%", "원자%": "at.%", "mol%": "mol.%", "몰%": "mol.%",
    "PPM": "ppm", "PPB": "ppb", "DPI": "dpi", "PPI": "ppi",
    # 데이터량·속도
    "byte": "B", "bytes": "B", "바이트": "B", "KB": "kB", "kbyte": "kB", "Mbyte": "MB", "Gbyte": "GB", "Tbyte": "TB",
    "b": "bit", "비트": "bit", "Kbit": "kbit",
    "bit/s": "bps", "Kbps": "kbps", "kbit/s": "kbps", "Mbit/s": "Mbps", "Gbit/s": "Gbps", "Tbit/s": "Tbps",
    # 각도·회전수·연산
    "deg": "°", "degree": "°", "degrees": "°", "도": "°", "라디안": "rad", "r/min": "rpm", "RPM": "rpm",
    "flops": "FLOPS", "Gflops": "GFLOPS", "Tflops": "TFLOPS", "Pflops": "PFLOPS",
    # 고시 원문에서 추가로 확인된 표기(2026-11-05)
    "Weighted TeraFLOPS": "WT", "가중 TeraFLOPS": "WT",
    "PS": "마력", "HP": "hp", "horsepower": "hp",
    "mAh/㎏": "Ah/kg", "mAh/g": "mAh/g", "kJ/㎏": "kJ/kg", "MJ/㎏": "MJ/kg", "GJ/㎥": "GJ/m3", "kJ/㎥": "kJ/m3",
    "㎜/s": "mm/s", "mm/sec": "mm/s", "㎜/sec": "mm/s", "mm/yr": "mm/year", "㎛/h": "μm/h", "um/h": "μm/h", "µm/h": "μm/h",
    "㎥/s": "m3/s", "㎥/sec": "m3/s", "m3/sec": "m3/s", "㎥/min": "m3/min", "㎥/h": "m3/h", "㎥/hr": "m3/h", "m3/hr": "m3/h",
    "m³/h": "m3/h", "m³/s": "m3/s", "m³/min": "m3/min",
    "l/min": "L/min", "ℓ/min": "L/min", "리터/분": "L/min", "l/h": "L/h", "ℓ/h": "L/h", "리터/시간": "L/h", "L/hr": "L/h",
    "㎤/min": "cm3/min", "cc/min": "cm3/min",
    "kg/hr": "kg/h", "㎏/h": "kg/h", "㎏/hr": "kg/h", "kg/sec": "kg/s",
    "Pa/hr": "Pa/h", "P": "poise", "푸아즈": "poise", "cps": "cP",
    "m²/g": "m2/g", "㎡/g": "m2/g",
    "A/㎟": "A/mm2", "A/mm²": "A/mm2", "mA/㎟": "mA/mm2", "mA/mm²": "mA/mm2", "A/us": "A/μs", "A/µs": "A/μs",
    "Ω/sq": "Ω/square", "ohm/square": "Ω/square", "ohm/sq": "Ω/square", "Ω·cm": "ohm-cm", "Ω-cm": "ohm-cm", "ohm·cm": "ohm-cm",
    "테슬라": "T", "tesla": "T", "밀리테슬라": "mT",
    "Gbyte/s": "GB/s", "GByte/s": "GB/s", "Mbyte/s": "MB/s", "Gb/s": "Gbps",
    "psec": "ps", "피코초": "ps",
    "아크 초": "arcsec", "아크초": "arcsec", "arc sec": "arcsec", "″": "arcsec", "deg/s": "°/s", "도/초": "°/s", "°/sec": "°/s",
    "deg/hr": "°/h", "°/hr": "°/h", "도/시간": "°/h",
    "µC/mm2": "μC/mm2", "uC/mm2": "μC/mm2", "µC/㎟": "μC/mm2", "μC/㎟": "μC/mm2",
    "mg/㎥": "mg/m3", "mg/m³": "mg/m3",
    "마이크론": "μm", "㎿h/kg": "MWh/kg", "nW": "nW", "uW": "μW", "µW": "μW",
    "mPa": "mPa", "큐비트": "qubit",
    "미크론": "μm", "Kg": "kg", "KG": "kg", "nautical mile": "해리", "nmi": "해리", "N·m": "Nm", "N-m": "Nm", "kN·m": "kNm",
    "N·s": "Ns", "kN·s": "kNs", "MN·s": "MNs", "kN·s/kg": "kNs/kg", "㎾/㎥": "kW/m3", "kW/m³": "kW/m3",
    "micro g": "μg(가속도)", "μg(가속도)": "μg(가속도)", "°/s²": "°/s2", "deg/s2": "°/s2",
    "milligal": "mGal", "밀리갈": "mGal", "uGal": "μGal", "µGal": "μGal",
    "nanotesla": "nT", "KHz": "kHz", "khz": "kHz", "Mhz": "MHz", "Ghz": "GHz",
    "kW/㎠": "kW/cm2", "kW/cm²": "kW/cm2", "W/㎠": "W/cm2", "W/cm²": "W/cm2", "J/㎠": "J/cm2", "J/cm²": "J/cm2",
    "frame/sec": "frame/s", "frames/s": "frame/s", "fps": "frame/s", "m²/s": "m2/s", "㎡/s": "m2/s",
    "mm/us": "mm/μs", "mm/µs": "mm/μs", "uA/lm": "μA/lm", "µA/lm": "μA/lm", "rad/s²": "rad/s2",
    "kg/㎡": "kg/m2", "kg/m²": "kg/m2", "nanovolt": "nV",
}


class UnitError(ValueError):
    """환산할 수 없는 단위 조합(종류 다름·환산표 없음·모르는 단위)."""


def normalize_unit(text):
    """원문 표기를 표준 표기로 바꾼다. 별칭표에 없으면 공백만 떼고 그대로 돌려준다."""
    if text is None:
        return ""
    unit = str(text).strip().replace("µ", MICRO)
    if unit in STANDARD_UNITS:
        return unit
    return ALIASES.get(unit, unit)


def aliases_of(unit):
    """표준 표기와 그 별칭 전부(표준 표기가 맨 앞). 모르는 단위는 글자 그대로 하나."""
    standard = normalize_unit(unit)
    names = [standard]
    for alias, target in ALIASES.items():
        if target == standard and alias not in names:
            names.append(alias)
    if standard == "μm":
        names.append("µm")
    return tuple(names)


def unit_kind(unit):
    """단위 종류(length·time·mass·…). 모르는 단위·빈 글은 None."""
    entry = STANDARD_UNITS.get(normalize_unit(unit))
    return entry[0] if entry else None


def _factor(standard):
    """기준 단위에 대한 배수를 정확한 분수로. 모르는 단위·환산하지 않는 단위는 None."""
    entry = STANDARD_UNITS.get(standard)
    if entry is None or entry[1] is None:
        return None
    numerator, _, denominator = entry[1].partition("/")
    return Fraction(numerator) / Fraction(denominator) if denominator else Fraction(numerator)


def _to_decimal(fraction):
    """분수 → Decimal. 유한 소수이면 정확한 값(끝의 0 없이), 아니면 현재 계산 정밀도에서 반올림한 값."""
    numerator, rest, twos, fives = fraction.numerator, fraction.denominator, 0, 0
    while rest % 2 == 0:
        rest //= 2
        twos += 1
    while rest % 5 == 0:
        rest //= 5
        fives += 1
    if rest != 1:
        return Decimal(numerator) / Decimal(fraction.denominator)
    places = max(twos, fives)
    digits = abs(numerator) * 10 ** places // fraction.denominator
    return Decimal((1 if numerator < 0 else 0, tuple(int(digit) for digit in str(digits)), -places))


def compare_units(a, b):
    """'same'(같은 글자) | 'convertible'(같은 종류이고 환산표 있음) | 'different_kind' | 'not_convertible'."""
    na, nb = normalize_unit(a), normalize_unit(b)
    if na == nb:
        return "same"
    ka, kb = unit_kind(na), unit_kind(nb)
    if ka is None or kb is None or ka != kb:
        return "different_kind"
    if _factor(na) is None or _factor(nb) is None:
        return "not_convertible"
    return "convertible"


def convert(value, from_unit, to_unit):
    """value(Decimal)를 from_unit에서 to_unit으로 환산한다. 같은 글자면 그대로. 환산 불가면 UnitError.

    분수로 계산해, 환산한 값이 유한 소수이면 정확히 그 값을 돌려준다(기준값과 같은 값이 같게 비교된다).
    """
    if not isinstance(value, Decimal):
        raise UnitError("값은 Decimal이어야 한다")
    relation = compare_units(from_unit, to_unit)
    if relation == "same":
        return value
    if relation != "convertible":
        raise UnitError(f"환산 불가({relation}): {from_unit!r} → {to_unit!r}")
    source, target = normalize_unit(from_unit), normalize_unit(to_unit)
    if not value.is_finite():
        raise UnitError("값은 유한한 수여야 한다")
    return _to_decimal(Fraction(value) * _factor(source) / _factor(target))
