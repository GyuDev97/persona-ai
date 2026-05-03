import 'package:flutter/material.dart';

class QuickPromptChip extends StatelessWidget {
  const QuickPromptChip({required this.label, required this.onTap, super.key});

  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return ActionChip(
      label: Text(label),
      onPressed: onTap,
      backgroundColor: const Color(0x220FD8C8),
      labelStyle: const TextStyle(color: Color(0xFFD7FFFA)),
      side: const BorderSide(color: Color(0x3348CFC2)),
    );
  }
}
