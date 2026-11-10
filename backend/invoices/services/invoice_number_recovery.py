import re


IDENTIFIER_FRAGMENT_PATTERN = re.compile(
    r"^[A-Za-z0-9]+"
    r"(?:[./_-][A-Za-z0-9]+)*"
    r"[./_-]?$"
)

HEADER_FIELD_LABELS = {
    "invoice",
    "number",
    "no",
    "date",
    "due",
    "subtotal",
    "total",
    "amount",
    "currency",
    "supplier",
    "vendor",
    "bill",
    "to",
    "tax",
    "vat",
    "payment",
    "terms",
    "description",
    "reference",
    "ref",
    "address",
    "phone",
    "email",
}


def _normalize_word(value):
    return re.sub(
        r"[^a-z0-9]",
        "",
        str(value).casefold(),
    )


def _build_header_rows(words, page_height):
    """
    Group PDF words into visual rows using their vertical positions.
    """

    header_limit = page_height * 0.30
    row_tolerance = max(2.5, page_height * 0.005)

    parsed_words = []

    for word in words:
        if len(word) < 5:
            continue

        x0, y0, x1, y1, text = word[:5]

        text = str(text).strip()

        if not text or float(y0) > header_limit:
            continue

        parsed_words.append({
            "x0": float(x0),
            "y0": float(y0),
            "x1": float(x1),
            "y1": float(y1),
            "text": text,
            "normalized": _normalize_word(text),
            "center_y": (
                float(y0) + float(y1)
            ) / 2,
        })

    parsed_words.sort(
        key=lambda item: (
            item["center_y"],
            item["x0"],
        )
    )

    rows = []

    for word in parsed_words:

        if (
            not rows
            or word["center_y"] - rows[-1]["center_y"]
            > row_tolerance
        ):
            rows.append({
                "center_y": word["center_y"],
                "words": [word],
            })

        else:
            row = rows[-1]
            row["words"].append(word)

            row["center_y"] = sum(
                item["center_y"]
                for item in row["words"]
            ) / len(row["words"])

    return rows


def _identifier_fragments_to_right(row, label):
    """
    Find identifier-like words immediately to the right of a label.
    """

    return [
        word
        for word in row["words"]
        if (
            word["x0"] >= label["x1"] - 4
            and IDENTIFIER_FRAGMENT_PATTERN.fullmatch(
                word["text"]
            )
        )
    ]


def _is_metadata_row(row, right_edge, tolerance):
    """
    Identify a new header field that should terminate recovery.
    """

    return any(
        word["normalized"] in HEADER_FIELD_LABELS
        and word["x0"] < right_edge - tolerance
        for word in row["words"]
    )


def _reconstruct_candidate(
    rows,
    invoice_row_index,
    number_row_index,
    first_fragment,
    second_fragment,
    alignment_tolerance,
):
    """
    Reconstruct a number from an arbitrary sequence of aligned fragments.

    The sequence starts on the Invoice row, continues on the Number row,
    and may extend through additional aligned rows.
    """

    fragments = [
        first_fragment["text"],
        second_fragment["text"],
    ]

    right_edge = first_fragment["x1"]

    line_spacing = (
        rows[number_row_index]["center_y"]
        - rows[invoice_row_index]["center_y"]
    )

    previous_center_y = rows[number_row_index]["center_y"]

    # Discover additional fragments without assuming a fixed count.
    for row in rows[number_row_index + 1:]:

        current_center_y = row["center_y"]

        vertical_gap = current_center_y - previous_center_y

        # Require spacing consistent with the observed header layout.
        if not (
            line_spacing * 0.55
            <= vertical_gap
            <= line_spacing * 1.65
        ):
            break

        # Stop before another metadata field, such as invoice date.
        if _is_metadata_row(
            row,
            right_edge,
            alignment_tolerance,
        ):
            break

        aligned_fragments = [
            word
            for word in row["words"]
            if (
                abs(word["x1"] - right_edge)
                <= alignment_tolerance
                and IDENTIFIER_FRAGMENT_PATTERN.fullmatch(
                    word["text"]
                )
            )
        ]

        # No candidate or multiple candidates: do not guess.
        if len(aligned_fragments) != 1:
            break

        fragments.append(
            aligned_fragments[0]["text"]
        )

        previous_center_y = current_center_y

    invoice_number = "".join(fragments)

    # Require a plausible alphanumeric invoice identifier.
    if not (
        len(invoice_number) >= 3
        and re.search(r"[A-Za-z]", invoice_number)
        and re.search(r"\d", invoice_number)
        and re.search(r"[-/]", invoice_number)
    ):
        return None

    return {
        "invoice_number": invoice_number,
        "fragments": fragments,
    }


def recover_split_invoice_number(page_words, page_sizes):
    """
    Recover a split invoice number using PDF word coordinates.

    Supports variable numbers of vertically aligned fragments.

    Returns None when the layout is ambiguous or unsupported.
    """

    candidates = []

    for page_number, words in page_words.items():

        page_size = page_sizes.get(page_number)

        if not page_size:
            continue

        page_width, page_height = page_size

        rows = _build_header_rows(
            words,
            page_height,
        )

        alignment_tolerance = max(
            5.0,
            page_width * 0.015,
        )

        label_alignment_tolerance = max(
            18.0,
            page_width * 0.04,
        )

        for invoice_row_index, invoice_row in enumerate(rows):

            invoice_labels = [
                word
                for word in invoice_row["words"]
                if word["normalized"] == "invoice"
            ]

            if len(invoice_labels) != 1:
                continue

            invoice_label = invoice_labels[0]

            for number_row_index in range(
                invoice_row_index + 1,
                len(rows),
            ):

                number_row = rows[number_row_index]

                vertical_gap = (
                    number_row["center_y"]
                    - invoice_row["center_y"]
                )

                if vertical_gap > 28:
                    break

                if vertical_gap < 3:
                    continue

                number_labels = [
                    word
                    for word in number_row["words"]
                    if word["normalized"] in {
                        "number",
                        "no",
                    }
                ]

                if len(number_labels) != 1:
                    continue

                number_label = number_labels[0]

                if abs(
                    invoice_label["x0"]
                    - number_label["x0"]
                ) > label_alignment_tolerance:
                    continue

                first_candidates = _identifier_fragments_to_right(
                    invoice_row,
                    invoice_label,
                )

                second_candidates = _identifier_fragments_to_right(
                    number_row,
                    number_label,
                )

                if (
                    len(first_candidates) != 1
                    or len(second_candidates) != 1
                ):
                    continue

                first_fragment = first_candidates[0]
                second_fragment = second_candidates[0]

                if abs(
                    first_fragment["x1"]
                    - second_fragment["x1"]
                ) > alignment_tolerance:
                    continue

                reconstructed = _reconstruct_candidate(
                    rows=rows,
                    invoice_row_index=invoice_row_index,
                    number_row_index=number_row_index,
                    first_fragment=first_fragment,
                    second_fragment=second_fragment,
                    alignment_tolerance=alignment_tolerance,
                )

                if reconstructed is None:
                    continue

                candidates.append({
                    **reconstructed,
                    "page": page_number,
                    "method": "aligned_header_fragments",
                })

    distinct_numbers = {
        candidate["invoice_number"]
        for candidate in candidates
    }

    # Multiple different reconstructed numbers are ambiguous.
    if len(distinct_numbers) != 1:
        return None

    return sorted(
        candidates,
        key=lambda item: (
            -len(item["fragments"]),
            item["page"],
        ),
    )[0]

