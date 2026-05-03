enum BubbleRole { user, assistant }

class ChatBubbleData {
  const ChatBubbleData({required this.role, required this.text});

  final BubbleRole role;
  final String text;
}
