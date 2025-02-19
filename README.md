# TravEx - AI-Powered Travel Guide Voice Assistant 🌎 🗣️

TravEx is an intelligent voice-based travel guide that helps users discover and learn about places in real-time through natural conversation. Built with advanced AI capabilities, it provides personalized recommendations while maintaining context and natural dialogue flow.

## 🌟 Features

- **Natural Voice Interaction**: Engage in natural conversations about places and recommendations
- **Context-Aware Responses**: System maintains conversation context for more relevant suggestions
- **Smart Place Discovery**: Uses semantic search to find relevant places based on user preferences
- **Real-Time Adaptation**: Adjusts recommendations based on user feedback and preferences
- **Intelligent Interruption Handling**: Allows users to interrupt and redirect the conversation naturally
- **Location-Aware**: Provides geographically relevant recommendations
- **Multi-Aspect Understanding**: Handles queries about various aspects (price, hours, atmosphere, etc.)

## 🛠️ Technology Stack

- **Voice Processing**: Twilio for voice calls and speech processing
- **Text-to-Speech**: ElevenLabs for natural voice generation
- **Language Understanding**: OpenAI GPT-4 for natural language processing
- **Vector Search**: Pinecone for semantic search and place discovery
- **Backend**: Python Flask for API handling
- **Data Storage**: Vector database for efficient place information retrieval

## 📋 Prerequisites

- Python 3.8+
- OpenAI API key
- ElevenLabs API key
- Twilio account and phone number
- Pinecone API key and index

## 🚀 Getting Started

1. Clone the repository:
```bash
git clone https://github.com/yourusername/travex.git
cd travex
```

2. Create and activate virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your API keys and configuration
```

5. Initialize the database:
```bash
python create_pinecone_embeddings.py
```

6. Run the application:
```bash
python run.py
```

## 🔧 Configuration

Create a `.env` file with the following variables:
```
OPENAI_API_KEY=your_openai_key
ELEVENLABS_API_KEY=your_elevenlabs_key
PINECONE_API_KEY=your_pinecone_key
PINECONE_ENVIRONMENT=your_pinecone_env
TWILIO_ACCOUNT_SID=your_twilio_sid
TWILIO_AUTH_TOKEN=your_twilio_token
TWILIO_PHONE_NUMBER=your_twilio_number
```

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details. Here are some ways you can help:

- Add new features
- Improve documentation
- Report bugs
- Submit fixes
- Suggest enhancements
- Add test cases

## 📝 Documentation

- [API Documentation](docs/API.md)
- [Architecture Overview](docs/ARCHITECTURE.md)
- [Development Guide](docs/DEVELOPMENT.md)
- [Testing Guide](docs/TESTING.md)

## 🎯 Roadmap

- [ ] Multi-language support
- [ ] User preference persistence
- [ ] Integration with booking systems
- [ ] Real-time availability checking
- [ ] Social features and shared experiences
- [ ] Mobile app integration
- [ ] Enhanced accessibility features

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- OpenAI for GPT-4 API
- ElevenLabs for voice generation
- Twilio for voice processing
- Pinecone for vector search
- All our contributors and supporters

## 📞 Support

For support, please:
1. Check the [documentation](docs/)
2. Search [existing issues](https://github.com/yourusername/travex/issues)
3. Create a new issue if needed

## 🔐 Security

Please report security vulnerabilities to ameeralns35@gmail.com 