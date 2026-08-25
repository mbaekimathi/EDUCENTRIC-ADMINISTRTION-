"""Dial codes used by employee registration phone input."""



FLAG_CDN = "https://flagcdn.com/w40/{code}.png"

FLAG_CDN_2X = "https://flagcdn.com/w80/{code}.png"





def flag_urls(iso):

    code = iso.lower()

    return {

        "flag_src": FLAG_CDN.format(code=code),

        "flag_srcset": f"{FLAG_CDN_2X.format(code=code)} 2x",

    }





_RAW_COUNTRIES = (

    {"iso": "KE", "name": "Kenya", "dial": "254", "nsn": 9, "placeholder": "7XX XXX XXX"},

    {"iso": "UG", "name": "Uganda", "dial": "256", "nsn": 9, "placeholder": "7XX XXX XXX"},

    {"iso": "TZ", "name": "Tanzania", "dial": "255", "nsn": 9, "placeholder": "7XX XXX XXX"},

    {"iso": "RW", "name": "Rwanda", "dial": "250", "nsn": 9, "placeholder": "7XX XXX XXX"},

    {"iso": "ET", "name": "Ethiopia", "dial": "251", "nsn": 9, "placeholder": "9XX XXX XXX"},

    {"iso": "NG", "name": "Nigeria", "dial": "234", "nsn": 10, "placeholder": "801 XXX XXXX"},

    {"iso": "GH", "name": "Ghana", "dial": "233", "nsn": 9, "placeholder": "2X XXX XXXX"},

    {"iso": "ZA", "name": "South Africa", "dial": "27", "nsn": 9, "placeholder": "8X XXX XXXX"},

    {"iso": "US", "name": "United States", "dial": "1", "nsn": 10, "placeholder": "(555) 000-0000"},

    {"iso": "GB", "name": "United Kingdom", "dial": "44", "nsn": 10, "placeholder": "7XXX XXXXXX"},

    {"iso": "IN", "name": "India", "dial": "91", "nsn": 10, "placeholder": "98XXX XXXXX"},

    {"iso": "AE", "name": "United Arab Emirates", "dial": "971", "nsn": 9, "placeholder": "5X XXX XXXX"},

)



PHONE_COUNTRIES = tuple({**item, **flag_urls(item["iso"])} for item in _RAW_COUNTRIES)





def country_by_iso(iso):

    iso = (iso or "KE").upper()

    for item in PHONE_COUNTRIES:

        if item["iso"] == iso:

            return item

    return PHONE_COUNTRIES[0]





def digits_only(value):

    return "".join(ch for ch in str(value or "") if ch.isdigit())





def normalize_phone(national_raw, country):

    """Build E.164-style +{dial}{nsn} from a local/national entry."""

    country = country or PHONE_COUNTRIES[0]

    dial = country["dial"]

    nsn_len = country["nsn"]

    digits = digits_only(national_raw)



    if digits.startswith(dial):

        digits = digits[len(dial) :]

    while digits.startswith("0"):

        digits = digits[1:]



    digits = digits[:nsn_len]

    if len(digits) != nsn_len:

        return ""

    return f"+{dial}{digits}"


