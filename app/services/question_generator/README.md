# Question Generator Tool

A ChatGPT-integrated tool engine for generating relevant Chinese questions from articles stored in JSON files.

## Features

- 🤖 **GPT-4 Integration**: Uses OpenAI's GPT-4.1 model for high-quality question generation
- 📁 **Interactive File Selection**: Choose which files to process via terminal interface
- 🔄 **Batch Processing**: Process multiple JSON files efficiently

- 📊 **Progress Tracking**: Real-time progress display during processing
- 🎯 **Smart Question Types**: Generates diverse question types (factual, comparative, practical, analytical)
- 🇨🇳 **Chinese Language**: All questions generated in simplified Chinese

## Installation

1. **Clone or download the project**

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables**:
   Create a `.env` file in the root directory:
   ```bash
   # OpenAI API Configuration
   OPENAI_API_KEY=your_openai_api_key_here
   
   # Optional: Override default settings
   # OPENAI_MODEL=gpt-4.1
   # QUESTIONS_PER_ARTICLE=3
   # MAX_TOKENS=1000
   # TEMPERATURE=0.7
   ```

4. **Get your OpenAI API key**:
   - Visit [OpenAI Platform](https://platform.openai.com/api-keys)
   - Create a new API key
   - Add it to your `.env` file

## Usage

### Interactive Mode (Recommended)

Run the tool interactively to select files:

```bash
python -m question_generator.main
```

This will:
1. Show available JSON files in the `data/` directory
2. Let you select which files to process
3. Display progress during processing
4. Show a summary of results

### Preview Mode

Preview files without processing them:

```bash
python -m question_generator.main preview
```

### Help

Show usage information:

```bash
python -m question_generator.main help
```

## File Structure

Your JSON files should contain articles with the following structure:

```json
[
  {
    "id": "unique_id",
    "title": "Article Title",
    "text": "Article content...",
    "raw_text": "Raw article content...",
    "question": null,  // Will be populated by the tool
    "source": "source_url",
    "language": "simplified-chinese"
  }
]
```

## Configuration

You can customize the tool behavior by modifying the `Config` class in `question_generator/config.py`:

- `QUESTIONS_PER_ARTICLE`: Number of questions to generate per article (default: 3)
- `MAX_TOKENS`: Maximum tokens for question generation (default: 1000)
- `TEMPERATURE`: Creativity level for question generation (default: 0.7)
- `DATA_DIR`: Directory containing JSON files (default: "data")


## Question Types Generated

The tool generates diverse question types:

1. **事实性问题** (Factual Questions): About specific data, costs, requirements
2. **比较性问题** (Comparative Questions): Comparing different options, regions, schools
3. **实用性问题** (Practical Questions): How to apply, prepare, operate
4. **分析性问题** (Analytical Questions): Why, impact, trends

## Example Output

After processing, your JSON files will be updated with generated questions:

```json
{
  "id": "20001",
  "title": "2025年澳洲音乐生留学费用多少明细",
  "text": "Article content...",
  "question": [
    "澳洲音乐类院校的学费范围是多少？",
    "悉尼音乐学院和墨尔本大学音乐专业的学费有什么差异？",
    "如何申请澳洲音乐留学奖学金？"
  ]
}
```



## Error Handling

The tool includes robust error handling:
- Invalid JSON files are skipped with error messages
- API errors are handled gracefully
- File permission issues are reported
- Processing continues even if individual articles fail

## Troubleshooting

### Common Issues

1. **"OpenAI API key not found"**
   - Check that your `.env` file exists and contains the API key
   - Verify the API key is valid and has sufficient credits

2. **"No JSON files found"**
   - Ensure JSON files are in the `data/` directory
   - Check file permissions

3. **"Invalid JSON format"**
   - Validate your JSON files using a JSON validator
   - Check for syntax errors

4. **API rate limits**
   - The tool includes delays between API calls
   - Consider processing smaller batches if needed

## Contributing

Feel free to contribute improvements:
- Bug reports
- Feature requests
- Code improvements
- Documentation updates

## License

This project is part of the CSSA-DA chatbot project.
