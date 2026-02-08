# Workflow Patterns for Skills

Proven patterns for multi-step processes in AI agent skills.

## Sequential Workflows

For tasks with clear step-by-step progression:

```markdown
## Workflow

1. **Validate Input**
   - Check all required fields present
   - Verify format and data types
   - Fail fast with clear error messages

2. **Gather Context**
   - Load relevant references if needed
   - Check for existing related work
   - Identify dependencies

3. **Execute Core Process**
   - Step A: [specific action]
   - Step B: [specific action]
   - Step C: [specific action]

4. **Validate Output**
   - Check completeness
   - Verify quality standards
   - Format per requirements

5. **Deliver Results**
   - Present in requested format
   - Include summary and next steps
   - Offer follow-up options
```

## Conditional Workflows

For tasks with branching logic:

```markdown
## Workflow

1. **Analyze Request Type**
   - If [condition A]: Follow path 1
   - If [condition B]: Follow path 2
   - Otherwise: Ask for clarification

2. **Path 1: [Scenario Name]**
   - Step 1...
   - Step 2...

3. **Path 2: [Scenario Name]**
   - Step 1...
   - Step 2...

4. **Converge and Deliver**
   - Common validation
   - Standard output format
```

## Iterative Workflows

For tasks requiring refinement:

```markdown
## Workflow

1. **Initial Draft**
   - Generate first version
   - Apply core requirements

2. **Review Cycle**
   - Check against quality criteria
   - Identify gaps or issues
   - If issues found: refine and repeat
   - If satisfactory: proceed

3. **Finalization**
   - Apply polish and formatting
   - Final validation
   - Deliver
```

## Data Processing Workflows

For ETL and analysis tasks:

```markdown
## Workflow

1. **Extract**
   - Load data from source
   - Validate integrity
   - Handle errors gracefully

2. **Transform**
   - Clean and normalize
   - Apply business logic
   - Enrich with context

3. **Load**
   - Format for destination
   - Write to output
   - Verify success

4. **Report**
   - Summarize results
   - Note any anomalies
   - Provide metrics
```

## Best Practices

### Clear Decision Points

Always specify decision criteria:

❌ **Vague:**
```
2. Process the data appropriately
```

✅ **Clear:**
```
2. Process Based on Data Type
   - If CSV: Use pandas DataFrame
   - If JSON: Use json.loads()
   - If binary: Use appropriate decoder
   - If unknown: Ask user for format
```

### Error Handling

Include explicit error paths:

```markdown
## Workflow

1. **Attempt Operation**
   - Try primary method
   - If fails: Log error details

2. **Fallback Strategy**
   - If error is [type A]: Try alternative method
   - If error is [type B]: Ask user for input
   - If unrecoverable: Explain limitation clearly

3. **Recovery or Graceful Exit**
   - Present partial results if available
   - Suggest next steps
   - Don't leave user hanging
```

### Progressive Complexity

Start simple, add complexity only as needed:

```markdown
## Workflow

### Basic Usage (most common)
1. Simple step A
2. Simple step B
3. Done

### Advanced Usage (optional)
For complex cases requiring [X]:
1. Advanced step A
2. Advanced step B
3. See references/advanced.md for details
```

## Anti-Patterns to Avoid

### ❌ Over-Specification

Don't micro-manage what the AI already knows:

```markdown
1. Read the file
   a. Open file handle
   b. Read bytes
   c. Decode UTF-8
   d. Close handle
```

### ❌ Under-Specification

Don't leave critical decisions unclear:

```markdown
1. Process the data
2. Generate output
```

### ❌ Hidden Complexity

Don't hide important steps:

```markdown
1. Prepare data
2. Magic happens here
3. Present results
```

✅ **Better:**
```markdown
1. Prepare data (normalize, validate)
2. Apply transformation (see references/algorithm.md)
3. Post-process (format, quality check)
4. Present results
```

## Examples from Production Skills

### Example: Document Processing Skill

```markdown
## Workflow

1. **Validate Document**
   - Check file format (.docx, .pdf, .txt)
   - Verify file is readable
   - Check size < 10MB

2. **Extract Content**
   - If DOCX: Use python-docx to preserve formatting
   - If PDF: Use pdfplumber for text + layout
   - If TXT: Read directly with UTF-8 encoding

3. **Process per Request**
   - Summarize: Use sliding window for long docs
   - Analyze: Apply domain-specific patterns
   - Transform: Apply requested changes

4. **Quality Check**
   - Verify output completeness
   - Check for encoding issues
   - Validate against requirements

5. **Deliver**
   - Format in requested output type
   - Include metadata (word count, etc.)
   - Offer follow-up options
```

### Example: API Integration Skill

```markdown
## Workflow

1. **Prepare Request**
   - Load API credentials from environment
   - Build request payload from user input
   - Validate required fields present

2. **Execute API Call**
   - Make HTTP request with retry logic
   - Handle rate limiting (wait and retry)
   - Capture response and status code

3. **Handle Response**
   - If 200: Parse and process data
   - If 4xx: Explain user error clearly
   - If 5xx: Retry up to 3 times
   - If network error: Report and suggest alternatives

4. **Process Results**
   - Transform API data to user-friendly format
   - Apply any filtering or sorting
   - Enrich with context if helpful

5. **Present**
   - Format in requested style (JSON, table, prose)
   - Highlight key findings
   - Offer to drill deeper if relevant
```

---

**Use these patterns as starting points.** Adapt to your specific domain and task requirements.
