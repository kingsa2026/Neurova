/**
 * I18nManager - 统一国际化库
 *
 * 职责：统一管理应用多语言切换、字符串资源引用、系统语言检测
 * 设计：单例模式；通过 StateManager 持久化当前语言；通过 EventBus 广播语言切换事件
 *
 * 用法：
 *   const i18nMgr = I18nManager.getInstance();
 *   i18nMgr.setLocale('en-US');
 *   // 在组件中通过 $r 引用资源，由系统按当前 locale 自动解析
 *   Text(i18nMgr.t('login_title'))
 */

import { i18n } from '@kit.LocalizationKit';
import { Logger } from '../logger/Logger';
import { EventBus } from '../bus/EventBus';
import { StateManager } from '../state/StateManager';

/** 支持的语言列表（破折号分隔的 BCP 47 风格） */
export type Locale = 'zh-CN' | 'en-US' | 'ja-JP' | 'ko-KR' | 'fr-FR' |
  'de-DE' | 'es-ES' | 'ru-RU' | 'ar-SA' | 'hi-IN' | 'it-IT';

/** 语言切换事件名 */
export const LANGUAGE_CHANGED_EVENT = 'language:changed';

/** StateManager 中存储当前语言的 key */
const STATE_KEY_LANGUAGE = 'app:language';

/** 默认语言 */
const DEFAULT_LOCALE: Locale = 'zh-CN';

/** 支持的语言列表 */
const SUPPORTED_LOCALES: Locale[] = [
  'zh-CN', 'en-US', 'ja-JP', 'ko-KR', 'fr-FR',
  'de-DE', 'es-ES', 'ru-RU', 'ar-SA', 'hi-IN', 'it-IT',
];

/** Locale 标识（破折号） → resources 目录名（下划线）映射 */
const LOCALE_TO_RESOURCE_DIR: Record<Locale, string> = {
  'zh-CN': 'zh_CN',
  'en-US': 'en_US',
  'ja-JP': 'ja_JP',
  'ko-KR': 'ko_KR',
  'fr-FR': 'fr_FR',
  'de-DE': 'de_DE',
  'es-ES': 'es_ES',
  'ru-RU': 'ru_RU',
  'ar-SA': 'ar_SA',
  'hi-IN': 'hi_IN',
  'it-IT': 'it_IT',
};

/** 语言切换事件负载 */
export interface LanguageChangedPayload {
  from: Locale;
  to: Locale;
}

export class I18nManager {
  private static instance: I18nManager;
  private logger: Logger = Logger.getInstance();
  private bus: EventBus = EventBus.getInstance();
  private state: StateManager = StateManager.getInstance();
  /** 当前语言（缓存，避免频繁读 StateManager） */
  private currentLocale: Locale;

  private constructor() {
    // 从 StateManager 恢复上次的语言，默认中文
    const saved = this.state.get<Locale>(STATE_KEY_LANGUAGE, DEFAULT_LOCALE);
    this.currentLocale = this.normalizeLocale(saved);
    this.logger.info('I18nManager', `初始化语言: ${this.currentLocale}`);
  }

  static getInstance(): I18nManager {
    if (!I18nManager.instance) {
      I18nManager.instance = new I18nManager();
    }
    return I18nManager.instance;
  }

  /** 获取当前语言 */
  getCurrentLocale(): Locale {
    return this.currentLocale;
  }

  /** 切换语言：写入 StateManager，并广播 language:changed 事件 */
  setLocale(locale: Locale): void {
    const normalized = this.normalizeLocale(locale);
    if (normalized === this.currentLocale) {
      this.logger.debug('I18nManager', `语言未变化，跳过切换: ${normalized}`);
      return;
    }
    const previous = this.currentLocale;
    this.currentLocale = normalized;
    // 持久化到 StateManager
    this.state.set<Locale>(STATE_KEY_LANGUAGE, normalized);
    // 广播事件，携带 { from, to } 便于订阅者刷新 UI
    const payload: LanguageChangedPayload = { from: previous, to: normalized };
    this.bus.emit(LANGUAGE_CHANGED_EVENT, payload);
    this.logger.info('I18nManager', `语言切换: ${previous} → ${normalized}`);
  }

  /** 返回支持的所有语言 */
  getSupportedLocales(): Locale[] {
    return SUPPORTED_LOCALES.slice();
  }

  /**
   * 资源引用：返回 ArkUI Resource，由系统按当前 locale 自动取对应资源
   *
   * 用法：Text(i18nMgr.t('login_title'))
   *
   * 说明：$r 是 ArkUI 内置资源引用构造器，传入 'app.string.{key}' 形式，
   * 系统会按当前 locale 自动从 resources/{locale}/element/string.json 取值。
   */
  t(key: string): Resource {
    return $r(`app.string.${key}`);
  }

  /** 返回指定 locale 对应的 resources 目录名（如 'zh-CN' → 'zh_CN'） */
  getResourceDir(locale: Locale): string {
    return LOCALE_TO_RESOURCE_DIR[locale] ?? LOCALE_TO_RESOURCE_DIR[DEFAULT_LOCALE];
  }

  /**
   * 检测系统语言并映射到支持的语言
   * 使用 @kit.LocalizationKit 的 i18n 模块读取系统语言
   */
  detectSystemLocale(): Locale {
    try {
      // i18n.getSystemLanguage 返回 BCP 47 语言标签，如 'zh-Hans-CN'、'en-US'
      const sysLang: string = i18n.getSystemLanguage();
      this.logger.debug('I18nManager', `系统语言: ${sysLang}`);
      return this.mapSystemLanguage(sysLang);
    } catch (e) {
      this.logger.error('I18nManager', '检测系统语言失败，回退默认', e as Error);
      return DEFAULT_LOCALE;
    }
  }

  /** 将系统语言字符串映射到支持的 Locale */
  private mapSystemLanguage(sysLang: string): Locale {
    if (!sysLang) {
      return DEFAULT_LOCALE;
    }
    const lower = sysLang.toLowerCase();

    // 优先精确匹配完整 locale（如 'zh-cn'、'en-us'）
    for (const loc of SUPPORTED_LOCALES) {
      if (lower === loc.toLowerCase()) {
        return loc;
      }
    }

    // 兼容带脚本子标签的语言标签（如 'zh-hans-cn'）：取末尾两段拼接匹配
    const segments = lower.split('-');
    if (segments.length >= 3) {
      const tail = `${segments[segments.length - 2]}-${segments[segments.length - 1]}`;
      for (const loc of SUPPORTED_LOCALES) {
        if (tail === loc.toLowerCase()) {
          return loc;
        }
      }
    }

    // 仅按主语言匹配（如 'zh' → 'zh-CN'，'ja' → 'ja-JP'）
    const primary = segments[0];
    const byPrimary: Record<string, Locale> = {
      zh: 'zh-CN',
      en: 'en-US',
      ja: 'ja-JP',
      ko: 'ko-KR',
      fr: 'fr-FR',
      de: 'de-DE',
      es: 'es-ES',
      ru: 'ru-RU',
      ar: 'ar-SA',
      hi: 'hi-IN',
      it: 'it-IT',
    };
    if (byPrimary[primary]) {
      return byPrimary[primary];
    }

    this.logger.warn('I18nManager', `无法识别的系统语言: ${sysLang}，回退默认`);
    return DEFAULT_LOCALE;
  }

  /** 校验并规范化 Locale，不支持的值回退到默认 */
  private normalizeLocale(locale: Locale): Locale {
    return SUPPORTED_LOCALES.includes(locale) ? locale : DEFAULT_LOCALE;
  }
}
