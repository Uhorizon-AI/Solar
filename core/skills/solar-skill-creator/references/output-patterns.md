# Output Format Patterns for Skills

Effective patterns for specifying AI agent output requirements.

## The Template Pattern

Provide exact templates for consistent output:

```markdown
## Output Format

Use this exact structure:

\`\`\`json
{
  "status": "success" | "error",
  "result": {
    "field1": "value",
    "field2": 123
  },
  "metadata": {
    "timestamp": "ISO-8601",
    "confidence": 0.95
  }
}
\`\`\`
```

## The Example Pattern

Show concrete examples instead of describing:

❌ **Abstract description:**
```markdown
Output should be a summary in paragraph form with key points highlighted.
```

✅ **Concrete example:**
```markdown
## Output Format

Example output:

> **Summary:** The document discusses three main themes: innovation,
> sustainability, and growth. **Key Finding:** Revenue increased 45% YoY.
> **Recommendation:** Focus on sustainable practices for long-term growth.
```

## The Progressive Detail Pattern

Start with required structure, add optional enhancements:

```markdown
## Output Format

### Required
- Clear answer to the question
- Sources cited [1][2][3]
- Confidence level (high/medium/low)

### Optional (if relevant)
- Visual representation (table, chart suggestion)
- Related questions to explore
- Next steps or action items
```

## The Validation Checklist Pattern

Specify quality criteria as checklist:

```markdown
## Output Requirements

Before delivering, verify:
- [ ] All user questions answered directly
- [ ] Technical terms defined on first use
- [ ] Sources cited for factual claims
- [ ] Code examples are syntactically valid
- [ ] Edge cases and limitations noted
- [ ] Output is under 1000 words (unless requested otherwise)
```

## The Format Table Pattern

For structured data with multiple fields:

```markdown
## Output Format

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | string | Yes | Unique identifier |
| name | string | Yes | Display name |
| score | float | Yes | 0.0 to 1.0 |
| tags | array | No | Category tags |
| metadata | object | No | Additional info |
```

## The Style Guide Pattern

Define tone, length, and style:

```markdown
## Output Style

**Tone:** Professional but conversational  
**Length:** 200-400 words for summaries, no limit for analysis  
**Language:** Match user's language (EN/ES/etc.)  
**Format:** Markdown with headers, lists, and code blocks  
**Audience:** Technical leadership (avoid jargon, explain when needed)

**Prohibited:**
- Marketing speak or hype
- Unsupported claims
- Passive voice in recommendations
```

## The Conditional Format Pattern

Different outputs for different scenarios:

```markdown
## Output Format

### If user asks for summary:
- 3-5 bullet points
- Each under 50 words
- No technical jargon

### If user asks for analysis:
- Executive summary (1 paragraph)
- Detailed findings (sections with headers)
- Data tables or charts if relevant
- Recommendations (numbered list)

### If user asks for comparison:
- Side-by-side table
- Pros/cons for each option
- Clear recommendation with rationale
```

## Real-World Examples

### Example: Code Generation Skill

```markdown
## Output Format

Generated code must include:

1. **Working implementation**
   - Syntactically correct
   - Includes necessary imports
   - Handles edge cases

2. **Documentation**
   - Brief description (1-2 lines)
   - Parameter types and descriptions
   - Return value description
   - Example usage

3. **Testing guidance**
   - How to run the code
   - Expected input/output examples
   - Common errors to watch for

Example:

\`\`\`python
def calculate_roi(initial_cost: float, revenue: float) -> float:
    """
    Calculate return on investment as percentage.

    Args:
        initial_cost: Initial investment amount
        revenue: Total revenue generated

    Returns:
        ROI as percentage (e.g., 25.0 for 25%)
    """
    return ((revenue - initial_cost) / initial_cost) * 100

# Example usage:
roi = calculate_roi(1000, 1500)  # Returns 50.0 (50% ROI)
\`\`\`
```

### Example: Analysis Skill

```markdown
## Output Format

Structure analysis reports as:

# [Topic] Analysis

## Executive Summary
[2-3 sentences: main finding and implication]

## Key Findings

### Finding 1: [Title]
**Data:** [Specific metric or observation]  
**Insight:** [What this means]  
**Implication:** [Why it matters]

### Finding 2: [Title]
[Same structure]

## Recommendations

1. **[Action]** - [Rationale] - Priority: High/Medium/Low
2. **[Action]** - [Rationale] - Priority: High/Medium/Low

## Supporting Data

[Tables, charts, or detailed numbers]

## Methodology

[How analysis was performed, data sources, limitations]

---
*Analysis confidence: High/Medium/Low*  
*Last updated: [Date]*
```

### Example: Document Creation Skill

```markdown
## Output Format

Generated documents follow this structure:

### Header
- Document title (H1)
- Date and author (if provided)
- Document ID or version (if applicable)

### Body
- Section headers (H2, H3)
- Paragraphs: 3-5 sentences, single clear idea each
- Lists: Use for enumeration, steps, or features
- Code blocks: Syntax highlighted, include language
- Tables: For structured comparisons or data

### Footer
- Summary or conclusion
- Next steps or call to action
- References or sources

### Formatting Standards
- Bold for **emphasis** or **key terms**
- Italics for *foreign terms* or *titles*
- Code for `technical_terms` or `file_names`
- Links for [external references](url)
- Block quotes for citations:
  > "Direct quote from source"
```

## Anti-Patterns to Avoid

### ❌ Vague Requirements

```markdown
Make the output look professional and well-formatted.
```

### ❌ Format Description Instead of Example

```markdown
The output should be a JSON object containing fields for status, 
data, and metadata, where data is an array of objects with id and 
name properties...
```

### ❌ Over-Prescription for Simple Tasks

```markdown
When outputting a simple answer:
1. Begin with a capital letter
2. End with proper punctuation
3. Use complete sentences
4. Check spelling
[...20 more obvious rules]
```

## Best Practices Summary

### DO ✅
- Show examples, not just descriptions
- Be specific about structure
- Include validation criteria
- Specify tone and audience
- Provide quality checklist
- Show error output format too

### DON'T ❌
- Leave format ambiguous
- Over-specify trivial details
- Forget about error cases
- Ignore user's context/language
- Assume AI knows your specific preferences

---

**The golden rule:** If you can show an example, do. Examples beat descriptions every time.
