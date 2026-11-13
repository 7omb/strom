from strom_tools.docs_check.doc_lines import Context, lines_of


def test_each_line_has_its_context() -> None:
    text = "---\ntitle: x\n---\n# A\n```\n`in code`\n```\n**Rejected**\n- old\n## B\ntext\n"
    assert [line.context for line in lines_of(text)] == [
        *[Context.FRONT_MATTER] * 3,
        Context.PROSE,
        *[Context.CODE] * 3,
        *[Context.REJECTED] * 2,
        *[Context.PROSE] * 2,
    ]
    assert [line.context for line in lines_of("text\n---\n")] == [Context.PROSE] * 2, "front matter only at the top"
