"""단위 모듈(units) 시험: 별칭 표준화·종류·환산·온도 비환산·모르는 단위."""
from decimal import Decimal
import unittest

from units import (
    ALIASES,
    STANDARD_UNITS,
    UnitError,
    aliases_of,
    compare_units,
    convert,
    normalize_unit,
    unit_kind,
)


class NormalizeTests(unittest.TestCase):
    def test_aliases_map_to_standard_notation(self):
        self.assertEqual(normalize_unit("㎛"), "μm")
        self.assertEqual(normalize_unit("um"), "μm")
        self.assertEqual(normalize_unit("µm"), "μm")  # U+00B5 마이크로 기호
        self.assertEqual(normalize_unit("나노"), "nm")
        self.assertEqual(normalize_unit("나노미터"), "nm")
        self.assertEqual(normalize_unit("리터"), "L")
        self.assertEqual(normalize_unit("Km"), "km")
        self.assertEqual(normalize_unit("톤"), "t")
        self.assertEqual(normalize_unit("℃"), "℃")
        self.assertEqual(normalize_unit("°C"), "℃")
        self.assertEqual(normalize_unit("uF/mm3"), "μF/mm3")
        self.assertEqual(normalize_unit("hr"), "시간")
        self.assertEqual(normalize_unit("years"), "년")

    def test_standard_notation_is_a_fixed_point(self):
        for unit in STANDARD_UNITS:
            self.assertEqual(normalize_unit(unit), unit)
        for alias, standard in ALIASES.items():
            self.assertEqual(normalize_unit(alias), standard, alias)
            self.assertEqual(normalize_unit(standard), standard, alias)

    def test_unknown_unit_is_returned_stripped(self):
        self.assertEqual(normalize_unit("  dose/lot "), "dose/lot")
        self.assertEqual(normalize_unit("가"), "가")
        self.assertEqual(normalize_unit(""), "")
        self.assertEqual(normalize_unit("   "), "")

    def test_aliases_of_includes_standard_and_aliases(self):
        names = aliases_of("nm")
        self.assertIn("nm", names)
        self.assertIn("나노", names)
        self.assertIn("㎚", names)
        self.assertEqual(aliases_of("dose/lot"), ("dose/lot",))
        self.assertEqual(aliases_of("um")[0], "μm")


class KindTests(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(unit_kind("nm"), "length")
        self.assertEqual(unit_kind("㎛"), "length")
        self.assertEqual(unit_kind("시간"), "time")
        self.assertEqual(unit_kind("년"), "time")
        self.assertEqual(unit_kind("kg"), "mass")
        self.assertEqual(unit_kind("톤"), "mass")
        self.assertEqual(unit_kind("GHz"), "frequency")
        self.assertEqual(unit_kind("kW"), "power")
        self.assertEqual(unit_kind("kWh"), "energy")
        self.assertEqual(unit_kind("Wh/kg"), "energy_density_mass")
        self.assertEqual(unit_kind("Wh/L"), "energy_density_volume")
        self.assertEqual(unit_kind("℃"), "temperature")
        self.assertEqual(unit_kind("K"), "temperature")
        self.assertEqual(unit_kind("MPa"), "pressure")
        self.assertEqual(unit_kind("bar"), "pressure")
        self.assertEqual(unit_kind("g/cm3"), "density")
        self.assertEqual(unit_kind("%"), "ratio")
        self.assertEqual(unit_kind("ppm"), "ratio")
        self.assertEqual(unit_kind("dpi"), "ratio")
        self.assertEqual(unit_kind("mA"), "current")
        self.assertEqual(unit_kind("kV"), "voltage")
        self.assertEqual(unit_kind("Gbps"), "data_rate")
        self.assertEqual(unit_kind("GB"), "data")
        self.assertEqual(unit_kind("lbf"), "force")
        self.assertIsNone(unit_kind("dose/lot"))
        self.assertIsNone(unit_kind("단"))
        self.assertIsNone(unit_kind(""))


class ConvertTests(unittest.TestCase):
    def test_length_time_mass_and_others_convert_exactly(self):
        self.assertEqual(convert(Decimal("0.8"), "um", "nm"), Decimal("800"))
        self.assertEqual(convert(Decimal("1"), "km", "m"), Decimal("1000"))
        self.assertEqual(convert(Decimal("1"), "인치", "mm"), Decimal("25.4"))
        self.assertEqual(convert(Decimal("2"), "시간", "분"), Decimal("120"))
        self.assertEqual(convert(Decimal("1"), "일", "시간"), Decimal("24"))
        self.assertEqual(convert(Decimal("3"), "톤", "kg"), Decimal("3000"))
        self.assertEqual(convert(Decimal("2.5"), "GHz", "MHz"), Decimal("2500"))
        self.assertEqual(convert(Decimal("1"), "kWh", "Wh"), Decimal("1000"))
        self.assertEqual(convert(Decimal("1"), "MPa", "kPa"), Decimal("1000"))
        self.assertEqual(convert(Decimal("1"), "bar", "kPa"), Decimal("100"))
        self.assertEqual(convert(Decimal("1"), "g/cm3", "kg/m3"), Decimal("1000"))
        self.assertEqual(convert(Decimal("1"), "A", "mA"), Decimal("1000"))
        self.assertEqual(convert(Decimal("1"), "kV", "V"), Decimal("1000"))
        self.assertEqual(convert(Decimal("1"), "Gbps", "Mbps"), Decimal("1000"))
        self.assertEqual(convert(Decimal("1"), "byte", "bit"), Decimal("8"))
        self.assertEqual(convert(Decimal("1"), "Wh/kg", "Wh/kg"), Decimal("1"))

    def test_watt_hour_family_is_3600_joules_1_3_3(self):
        # 1.3.2까지는 1 Wh를 1 J로 두어 3,600배 작게 환산했다.
        self.assertEqual(convert(Decimal("1"), "Wh", "J"), Decimal("3600"))
        self.assertEqual(convert(Decimal("5"), "Wh", "kJ"), Decimal("18"))
        self.assertEqual(convert(Decimal("1"), "kWh", "MJ"), Decimal("3.6"))
        self.assertEqual(convert(Decimal("1"), "MWh", "GJ"), Decimal("3.6"))
        self.assertEqual(convert(Decimal("1"), "GWh", "GJ"), Decimal("3600"))
        self.assertEqual(convert(Decimal("7.2"), "kJ", "Wh"), Decimal("2"))
        self.assertEqual(convert(Decimal("1"), "킬로와트시", "kcal"), Decimal("3600000") / Decimal("4184"))
        self.assertEqual(convert(Decimal("1"), "kWh", "Wh"), Decimal("1000"))
        self.assertEqual(convert(Decimal("2"), "kWh/kg", "Wh/kg"), Decimal("2000"))  # 에너지밀도는 따로 둔 종류

    def test_divided_factors_convert_exactly_1_3_3(self):
        # 1.3.2까지는 끊긴 소수 계수라 환산하면 기준값과 정확히 같은 값이 조금 크게 나왔다(600.0000000000000480).
        exact = (
            ("2160", "km/h", "m/s", "600"), ("1944", "km/h", "m/s", "540"), ("55.56", "km/h", "kn", "30"),
            ("30", "kn", "km/h", "55.56"), ("9", "kn", "m/s", "4.63"), ("720", "arcsec", "°", "0.2"),
            ("180", "arcsec", "°", "0.05"), ("21600", "°/h", "°/s", "6"), ("0.5", "°/s", "°/h", "1800"),
            ("120", "m3/min", "m3/s", "2"), ("7200", "m3/h", "m3/s", "2"), ("60", "m3/h", "m3/min", "1"),
            ("1000", "L/min", "m3/min", "1"), ("3600000", "L/h", "m3/s", "1"), ("1000", "L/h", "m3/h", "1"),
            ("60", "L/h", "L/min", "1"), ("1000000", "cm3/min", "m3/min", "1"), ("1000", "cm3/min", "L/min", "1"),
            ("760", "Torr", "atm", "1"), ("760", "mmHg", "Pa", "101325"), ("1", "atm", "Torr", "760"),
            ("1", "hp", "W", "745.69987158227022"),
        )
        for value, source, target, expected in exact:
            result = convert(Decimal(value), source, target)
            self.assertEqual(result, Decimal(expected), (value, source, target))
            self.assertEqual(str(result), expected, (value, source, target))  # 끝에 군더더기 자리 없음

    def test_non_terminating_results_round_at_working_precision_1_3_3(self):
        # 끝나지 않는 소수는 28자리에서 반올림한다(참값과의 차이는 마지막 자리 아래).
        self.assertEqual(convert(Decimal("100"), "km/h", "m/s"), Decimal("250") / Decimal("9"))
        self.assertEqual(convert(Decimal("1"), "arcsec", "°"), Decimal("1") / Decimal("3600"))
        self.assertEqual(convert(Decimal("1"), "Torr", "Pa"), Decimal("101325") / Decimal("760"))
        # psi는 lbf/in²의 정의(4.4482216152605 N ÷ 0.00064516 m²)에서 만든다.
        self.assertEqual(convert(Decimal("1"), "psi", "Pa"), Decimal("4.4482216152605") / Decimal("0.00064516"))
        self.assertEqual(str(convert(Decimal("0.00064516"), "psi", "Pa")), "4.4482216152605")

    def test_conversion_keeps_sign_zero_and_many_digits_1_3_3(self):
        self.assertEqual(convert(Decimal("-2160"), "km/h", "m/s"), Decimal("-600"))
        self.assertEqual(convert(Decimal("0"), "km/h", "m/s"), Decimal("0"))
        self.assertEqual(convert(Decimal("-0"), "kWh", "MJ"), Decimal("0"))
        self.assertEqual(convert(Decimal("3E+6"), "m", "km"), Decimal("3000"))
        # 자릿수가 많아도 유한 소수이면 한 자리도 줄이지 않는다.
        long_value = Decimal("123456789012345678901234567890.123456789")
        self.assertEqual(str(convert(long_value, "km", "m")), "123456789012345678901234567890123.456789")
        self.assertEqual(convert(Decimal("1"), "eV", "GJ"), Decimal("1.602176634E-28"))
        for bad in ("NaN", "Infinity", "-Infinity"):
            with self.assertRaises(UnitError):
                convert(Decimal(bad), "km/h", "m/s")

    def test_every_factor_reads_as_an_exact_fraction_1_3_3(self):
        from fractions import Fraction
        import units
        for unit, (kind, factor) in STANDARD_UNITS.items():
            if factor is None:
                self.assertIsNone(units._factor(unit), unit)
                continue
            value = units._factor(unit)
            self.assertIsInstance(value, Fraction, unit)
            self.assertGreater(value, 0, unit)
        self.assertEqual(units._factor("km/h"), Fraction(5, 18))
        self.assertEqual(units._factor("kn"), Fraction(463, 900))
        self.assertEqual(units._factor("kWh"), Fraction(3600000))
        self.assertEqual(units._factor("L/min"), Fraction(1, 60000))

    def test_same_unit_returns_same_value(self):
        self.assertEqual(convert(Decimal("7.25"), "단", "단"), Decimal("7.25"))
        self.assertEqual(convert(Decimal("3"), "", ""), Decimal("3"))

    def test_temperature_is_not_converted(self):
        """온도는 오프셋 때문에 환산하지 않는다. 같은 글자일 때만 비교한다."""
        with self.assertRaises(UnitError):
            convert(Decimal("100"), "℃", "K")
        self.assertEqual(convert(Decimal("100"), "°C", "℃"), Decimal("100"))

    def test_ratio_units_are_not_converted(self):
        with self.assertRaises(UnitError):
            convert(Decimal("1"), "%", "ppm")
        with self.assertRaises(UnitError):
            convert(Decimal("1"), "wt.%", "%")

    def test_different_kind_and_unknown_raise(self):
        with self.assertRaises(UnitError):
            convert(Decimal("1"), "kg", "m")
        with self.assertRaises(UnitError):
            convert(Decimal("1"), "dose/lot", "L")
        with self.assertRaises(UnitError):
            convert(Decimal("1"), "단", "축")


class CompareTests(unittest.TestCase):
    def test_compare_results(self):
        self.assertEqual(compare_units("nm", "nm"), "same")
        self.assertEqual(compare_units("㎛", "um"), "same")
        self.assertEqual(compare_units("", ""), "same")
        self.assertEqual(compare_units("단", "단"), "same")
        self.assertEqual(compare_units("nm", "㎛"), "convertible")
        self.assertEqual(compare_units("년", "시간"), "convertible")
        self.assertEqual(compare_units("℃", "K"), "not_convertible")
        self.assertEqual(compare_units("%", "ppm"), "not_convertible")
        self.assertEqual(compare_units("kg", "m"), "different_kind")
        self.assertEqual(compare_units("단", "축"), "different_kind")
        self.assertEqual(compare_units("nm", ""), "different_kind")


if __name__ == "__main__":
    unittest.main()
