import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;

/// Provider ids understood by the AutoMoto server.
const providerIds = ['nim', 'gemini', 'groq', 'openrouter', 'openai', 'claude'];

class ChatResult {
  ChatResult(this.text, this.provider, this.model, this.task, this.tried);
  final String text;
  final String provider;
  final String model;
  final String task;
  final List<dynamic> tried;
}

/// Thin client for the AutoMoto v4 API.
///
/// Everything sensitive (server token, BYOK keys) is kept in the platform
/// secure store: iOS Keychain / Android Keystore-backed EncryptedSharedPreferences.
class AutoMotoApi {
  AutoMotoApi({FlutterSecureStorage? storage})
      : _store = storage ??
            const FlutterSecureStorage(
              aOptions: AndroidOptions(encryptedSharedPreferences: true),
            );

  final FlutterSecureStorage _store;

  // Android emulator reaches the host machine at 10.0.2.2.
  static const defaultServer = 'http://10.0.2.2:8765';

  Future<String> serverUrl() async => (await _store.read(key: 'server_url')) ?? defaultServer;
  Future<void> setServerUrl(String v) => _store.write(key: 'server_url', value: v.trim());

  Future<String?> apiToken() => _store.read(key: 'api_token');
  Future<void> setApiToken(String v) => v.trim().isEmpty
      ? _store.delete(key: 'api_token')
      : _store.write(key: 'api_token', value: v.trim());

  Future<String?> providerKey(String id) => _store.read(key: 'key_$id');
  Future<void> setProviderKey(String id, String v) => v.trim().isEmpty
      ? _store.delete(key: 'key_$id')
      : _store.write(key: 'key_$id', value: v.trim());

  Future<void> forgetAll() => _store.deleteAll();

  Future<Map<String, String>> _keys() async {
    final out = <String, String>{};
    for (final id in providerIds) {
      final k = await providerKey(id);
      if (k != null && k.isNotEmpty) out[id] = k;
    }
    return out;
  }

  Future<Map<String, String>> _headers() async {
    final tok = await apiToken();
    return {
      'Content-Type': 'application/json',
      if (tok != null && tok.isNotEmpty) 'Authorization': 'Bearer $tok',
    };
  }

  Future<Map<String, dynamic>> _post(String path, Map<String, dynamic> body) async {
    final uri = Uri.parse('${await serverUrl()}$path');
    final res = await http
        .post(uri, headers: await _headers(), body: jsonEncode(body))
        .timeout(const Duration(seconds: 120));
    final data = res.body.isEmpty ? <String, dynamic>{} : jsonDecode(res.body) as Map<String, dynamic>;
    if (res.statusCode >= 400) {
      throw Exception(data['detail'] ?? data['error'] ?? 'HTTP ${res.statusCode}');
    }
    return data;
  }

  Future<List<dynamic>> providers() async {
    final data = await _post('/api/status', {'keys': await _keys()});
    return data['providers'] as List<dynamic>;
  }

  Future<ChatResult> chat(List<Map<String, dynamic>> messages, {String prefer = 'auto'}) async {
    final d = await _post('/api/chat', {
      'messages': messages,
      'prefer': prefer,
      'keys': await _keys(),
      'client': 'mobile', // server never offers desktop actions to phones
    });
    return ChatResult(
      d['text'] as String? ?? '',
      d['provider'] as String? ?? '?',
      d['model'] as String? ?? '?',
      d['task'] as String? ?? '',
      (d['tried'] as List<dynamic>?) ?? const [],
    );
  }
}
