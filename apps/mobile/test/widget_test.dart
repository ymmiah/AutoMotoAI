import 'package:flutter_test/flutter_test.dart';

import 'package:automoto_mobile/api.dart';

void main() {
  test('provider ids match the AutoMoto v4 server registry', () {
    expect(providerIds, ['nim', 'gemini', 'groq', 'openrouter', 'openai', 'claude']);
  });
}
