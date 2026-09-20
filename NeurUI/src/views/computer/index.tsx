import React, { useEffect, useState } from 'react';
import { PageContainer } from '@ant-design/pro-components';
import { ComputerView } from './ComputerView';
import { ComputerStats } from './ComputerStats';
import { ComputerList } from './ComputerList';
import { ComputerDetail } from './ComputerDetail';
import type { Route } from '@/types/router';

const ComputerRoute: Route = {
  path: '/computers',
  component: ComputerView,
  title: 'Computers',
  icon: 'desktop',
  permissions: ['computers:view'],
};

export default ComputerRoute;
